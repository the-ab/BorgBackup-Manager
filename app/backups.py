from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from tempfile import NamedTemporaryFile, mkdtemp

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.config import (
    BACKUP_DIR,
    BACKUP_MAX_COMPRESSION_RATIO,
    BACKUP_CACHE_MAX_FILE_BYTES,
    BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES,
    BACKUP_CACHE_MAX_ENTRIES,
    BACKUP_CACHE_MAX_COMPRESSION_RATIO,
    BACKUP_MAX_ENTRIES,
    BACKUP_MAX_FILE_BYTES,
    BACKUP_MAX_UNCOMPRESSED_BYTES,
    DATA_DIR,
    DATABASE_URL,
    SECURITY_DATABASE_PATH,
    SETTINGS_PATH,
    NOTIFICATION_SETTINGS_PATH,
    MANAGER_BORG_CACHE_DIR,
    MANAGER_BORG_SECURITY_DIR,
)


BACKUP_FORMAT = "borgbackup-manager-full-backup"
CACHE_BACKUP_FORMAT = "borgbackup-manager-cache-backup"
BACKUP_ENVELOPE_FORMAT = "borgbackup-manager-encrypted-backup"
BACKUP_MAGIC = b"BBM-BACKUP-1\n"
MIN_SUPPORTED_BACKUP_VERSION = "1.1.0"
MANAGER_BACKUP_NAME = re.compile(
    r"^borgbackup-manager-backup-v[0-9A-Za-z.+-]+-[0-9]{8}-[0-9]{6}-[a-zA-Z0-9_-]+\.(?:zip|bbm)$"
)
CACHE_BACKUP_NAME = re.compile(
    r"^borgbackup-manager-cache-v[0-9A-Za-z.+-]+-[0-9]{8}-[0-9]{6}-[a-zA-Z0-9_-]+\.(?:zip|bbm)$"
)
BACKUP_NAME = re.compile(
    r"^borgbackup-manager-(?:backup|cache)-v[0-9A-Za-z.+-]+-[0-9]{8}-[0-9]{6}-[a-zA-Z0-9_-]+\.(?:zip|bbm)$"
)
RESTORE_COMPONENTS = ("manager.db", "settings.json", "notifications.json", "ssh", "repository-ssh", "repository-keys", "tls", "security", "borg-cache", "borg-security")

ProgressCallback = Callable[[dict], None]


def _version_tuple(value: object) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", str(value or "").strip())
    if not match:
        raise ValueError("Backup enthält keine gültige BorgBackup-Manager-Version")
    return tuple(int(part) for part in match.groups())


def _require_supported_backup_version(metadata: dict) -> None:
    version = metadata.get("app_version")
    if _version_tuple(version) < _version_tuple(MIN_SUPPORTED_BACKUP_VERSION):
        raise ValueError(
            f"Backups vor BorgBackup Manager v{MIN_SUPPORTED_BACKUP_VERSION} werden nicht mehr unterstützt"
        )


def backup_type_from_manifest(manifest: dict) -> str:
    if manifest.get("format") == CACHE_BACKUP_FORMAT:
        return "cache"
    return "manager"


def _report(progress: ProgressCallback | None, **payload) -> None:
    if progress is not None:
        progress(payload)


def _label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")[:48]
    return cleaned or "manual"


def _database_path() -> Path:
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix) or DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        raise ValueError("Vollbackups werden derzeit nur für die persistente SQLite-Datenbank unterstützt")
    return Path(DATABASE_URL[len(prefix):])


def _sqlite_snapshot(destination: Path) -> None:
    source = sqlite3.connect(_database_path(), timeout=60)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _add_tree(archive: zipfile.ZipFile, source: Path, prefix: str, permissions: dict[str, int], *, skip_borg_locks: bool = False, progress: Callable[[int, int], None] | None = None) -> tuple[int, int]:
    count = 0
    total_bytes = 0
    if not source.is_dir():
        return count, total_bytes
    stack = [source]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if path.is_symlink():
                    continue
                if skip_borg_locks and path.name in {"lock.exclusive", "lock.roster"}:
                    continue
                if path.is_dir():
                    stack.append(path)
                    continue
                if not path.is_file():
                    continue
                arcname = f"data/{prefix}/{path.relative_to(source).as_posix()}"
                archive.write(path, arcname)
                info = path.stat()
                permissions[arcname] = stat.S_IMODE(info.st_mode) & 0o777
                count += 1
                total_bytes += int(info.st_size)
                if progress is not None:
                    progress(count, total_bytes)
            except OSError:
                continue
    return count, total_bytes


def _compression_settings(value: str) -> tuple[int, int | None, str]:
    normalized = (value or "standard").strip().lower()
    choices = {
        "none": (zipfile.ZIP_STORED, None, "none"),
        "fast": (zipfile.ZIP_DEFLATED, 1, "deflate-1"),
        "standard": (zipfile.ZIP_DEFLATED, 6, "deflate-6"),
        "maximum": (zipfile.ZIP_DEFLATED, 9, "deflate-9"),
    }
    if normalized not in choices:
        raise ValueError("Unbekannte Manager-Backup-Kompression")
    return choices[normalized]


def _migration_env() -> str:
    keys = (
        "TZ", "BBM_HTTPS_PORT", "BBM_TLS_HOSTS", "BBM_SESSION_TTL_SECONDS",
        "BBM_SESSION_IDLE_TIMEOUT_SECONDS", "BBM_SESSION_COOKIE_NAME", "BBM_SESSION_COOKIE_SECURE",
        "BBM_TRUSTED_PROXY_CIDRS", "BBM_LOGIN_RATE_WINDOW_SECONDS", "BBM_LOGIN_RATE_BLOCK_SECONDS",
        "BBM_LOGIN_RATE_MAX_PER_IP", "BBM_LOGIN_RATE_MAX_PER_IP_USER",
        "BBM_SECURITY_EVENT_RETENTION_DAYS", "BBM_SECURITY_EVENT_MAX_ROWS",
        "BBM_BACKUP_MAX_FILE_BYTES", "BBM_BACKUP_MAX_UNCOMPRESSED_BYTES",
        "BBM_BACKUP_MAX_ENTRIES", "BBM_BACKUP_MAX_COMPRESSION_RATIO",
        "BBM_BACKUP_CACHE_MAX_FILE_BYTES", "BBM_BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES",
        "BBM_BACKUP_CACHE_MAX_ENTRIES", "BBM_BACKUP_CACHE_MAX_COMPRESSION_RATIO",
        "BBM_COMMAND_TIMEOUT", "BBM_APPEARANCE",
        "BBM_REPOSITORY_SIZE_AFTER_RUN", "BBM_REPOSITORY_PUBLIC_HOST",
        "BBM_REPOSITORY_SSH_PORT", "BBM_BORG_UID", "BBM_BORG_GID",
        "BBM_STORAGE_GUARD_ENABLED", "BBM_STORAGE_GUARD_THRESHOLD_PERCENT",
        "BBM_HEALTH_REQUIRE_SSHD", "BBM_LOG_MAX_BYTES", "BBM_LOG_ROTATIONS",
        "BBM_DATA_PATH", "BBM_REPOSITORY_PATH", "BBM_ARCHIVE_MOUNT_PATH",
    )
    lines = []
    for key in keys:
        value = os.getenv(key, "")
        if "\n" in value or "\r" in value:
            raise ValueError(f"Umgebungswert {key} enthält einen Zeilenumbruch")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _write_plain_backup(
    destination: Path,
    app_version: str,
    label: str,
    *,
    compression: str = "standard",
    progress: ProgressCallback | None = None,
) -> dict:
    """Write a manager-only backup ZIP.

    Borg caches deliberately live in their own cache-backup artifact. Keeping
    the control-plane backup small makes update/restore operations predictable
    even when repositories are several TiB large.
    """
    with NamedTemporaryFile(prefix="bbm-db-", suffix=".sqlite3", dir=DATA_DIR, delete=False) as temporary:
        snapshot = Path(temporary.name)
    try:
        _report(progress, stage="database", message="Datenbank-Snapshot wird erstellt …", percent=10.0)
        _sqlite_snapshot(snapshot)
        _report(progress, stage="manager_data", message="Manager-Daten und Sicherheitseinstellungen werden verpackt …", percent=28.0)
        permissions: dict[str, int] = {}
        compression_type, compression_level, compression_name = _compression_settings(compression)
        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": 6,
            "backup_type": "manager",
            "app_version": app_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "encrypted": False,
            "repository_data_included": False,
            "run_logs_included": False,
            # Retain explicit false flags so old readers do not infer cache data.
            "borg_cache_included": False,
            "borg_security_included": False,
            "client_borg_cache_included": False,
            "compression": compression_name,
            "includes": ["database", "security_database", "master_key", "settings", "notification_settings", "migration_environment"],
        }
        zip_kwargs = {"compression": compression_type}
        if compression_level is not None:
            zip_kwargs["compresslevel"] = compression_level
        with zipfile.ZipFile(destination, "w", **zip_kwargs) as archive:
            archive.writestr("migration.env", _migration_env())
            archive.write(snapshot, "data/manager.db")
            permissions["data/manager.db"] = 0o600
            if SETTINGS_PATH.is_file():
                archive.write(SETTINGS_PATH, "data/settings.json")
                permissions["data/settings.json"] = 0o600
            if NOTIFICATION_SETTINGS_PATH.is_file():
                archive.write(NOTIFICATION_SETTINGS_PATH, "data/notifications.json")
                permissions["data/notifications.json"] = 0o600
            security_dir = DATA_DIR / "security"
            if SECURITY_DATABASE_PATH.is_file():
                with NamedTemporaryFile(prefix="bbm-security-", suffix=".sqlite3", dir=DATA_DIR, delete=False) as security_temporary:
                    security_snapshot = Path(security_temporary.name)
                try:
                    source = sqlite3.connect(SECURITY_DATABASE_PATH, timeout=60)
                    target = sqlite3.connect(security_snapshot)
                    try:
                        source.backup(target)
                        has_sessions = target.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
                        ).fetchone()
                        if has_sessions:
                            has_reload_tokens = target.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_reload_tokens'"
                            ).fetchone()
                            if has_reload_tokens:
                                target.execute("DELETE FROM session_reload_tokens")
                            target.execute("DELETE FROM sessions")
                            target.commit()
                    finally:
                        target.close(); source.close()
                    archive.write(security_snapshot, "data/security/security.db")
                    permissions["data/security/security.db"] = 0o600
                finally:
                    security_snapshot.unlink(missing_ok=True)
            for security_file in ("master.key",):
                path = security_dir / security_file
                if path.is_file() and not path.is_symlink():
                    archive.write(path, f"data/security/{security_file}")
                    permissions[f"data/security/{security_file}"] = 0o600
            _report(progress, stage="finalize_archive", message="Manager-Backup-Archiv wird abgeschlossen …", percent=74.0, current=None, total=None, bytes_done=0)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            archive.writestr("permissions.json", json.dumps(permissions, indent=2, sort_keys=True) + "\n")
        return manifest
    finally:
        snapshot.unlink(missing_ok=True)


def _write_cache_backup(
    destination: Path,
    app_version: str,
    label: str,
    *,
    include_manager_borg_cache: bool = True,
    include_client_borg_cache: bool = True,
    compression: str = "standard",
    progress: ProgressCallback | None = None,
) -> dict:
    """Write cache-only data without manager database, keys or settings."""
    if not (include_manager_borg_cache or include_client_borg_cache):
        raise ValueError("Cache-Backup benötigt mindestens Manager-Cache oder Client-Caches")
    permissions: dict[str, int] = {}
    compression_type, compression_level, compression_name = _compression_settings(compression)
    manifest = {
        "format": CACHE_BACKUP_FORMAT,
        "format_version": 1,
        "backup_type": "cache",
        "app_version": app_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "encrypted": False,
        "borg_cache_included": bool(include_manager_borg_cache),
        "borg_security_included": bool(include_manager_borg_cache),
        "client_borg_cache_included": bool(include_client_borg_cache),
        "client_borg_security_included": bool(include_client_borg_cache),
        "compression": compression_name,
        "includes": [],
    }
    zip_kwargs = {"compression": compression_type}
    if compression_level is not None:
        zip_kwargs["compresslevel"] = compression_level
    with zipfile.ZipFile(destination, "w", **zip_kwargs) as archive:
        if include_manager_borg_cache:
            _report(progress, stage="manager_cache", message="Manager-Borg-Cache und Borg-Sicherheitsstatus werden gesichert …", percent=8.0, current=0, bytes_done=0)

            def manager_cache_progress(files: int, source_bytes: int) -> None:
                _report(
                    progress, stage="manager_cache",
                    message="Manager-Borg-Cache und Borg-Sicherheitsstatus werden gesichert …",
                    percent=18.0, current=files, bytes_done=source_bytes,
                )

            cache_files, cache_bytes = _add_tree(
                archive, MANAGER_BORG_CACHE_DIR, "borg-cache", permissions,
                skip_borg_locks=True, progress=manager_cache_progress,
            )
            security_files, security_bytes = _add_tree(
                archive, MANAGER_BORG_SECURITY_DIR, "borg-security", permissions,
                progress=lambda files, source_bytes: manager_cache_progress(cache_files + files, cache_bytes + source_bytes),
            )
            manifest["borg_cache_files"] = cache_files
            manifest["borg_cache_source_bytes"] = cache_bytes
            manifest["borg_security_files"] = security_files
            manifest["borg_security_source_bytes"] = security_bytes
            manifest["includes"].extend(["borg_cache", "borg_security"])

        if include_client_borg_cache:
            from app.client_cache import client_cache_summary, collect_client_borg_caches
            base = 30.0 if include_manager_borg_cache else 8.0
            span = 45.0 if include_manager_borg_cache else 67.0
            _report(progress, stage="client_cache", message="Client-Borg-Caches werden vorbereitet …", percent=base, current=0, total=0, bytes_done=0)

            def client_progress(item: dict) -> None:
                total = max(1, int(item.get("total") or 1))
                index = max(1, int(item.get("index") or 1))
                event = str(item.get("event") or "")
                completed = index if event == "target_done" else index - 1
                percent = base + (span * max(0, min(total, completed)) / total)
                host_name = str(item.get("host_name") or "Gerät")
                repository_name = str(item.get("repository_name") or "Repository")
                status = str(item.get("status") or "")
                component = str(item.get("component") or "cache")
                security_status = str(item.get("security_status") or "")
                if event == "target_done" and status == "missing":
                    message = f"Client {index}/{total}: {host_name} · {repository_name} – Cache fehlt, Sicherheitsstatus {security_status or 'geprüft'}"
                elif event == "target_done" and status == "warning":
                    reason = str(item.get("reason") or "Client nicht erreichbar")
                    if len(reason) > 320:
                        reason = reason[:317] + "…"
                    message = f"WARNUNG: Client {index}/{total}: {host_name} · {repository_name} konnte nicht gesichert werden – {reason}"
                elif event == "target_done" and status.startswith("skipped_"):
                    message = f"Client {index}/{total}: {host_name} · {repository_name} – übersprungen"
                elif event == "target_done":
                    message = f"Client {index}/{total}: {host_name} · {repository_name} – Cache und Sicherheitsstatus verarbeitet"
                elif component == "security":
                    message = f"Client {index}/{total}: {host_name} · {repository_name} – Borg-Sicherheitsstatus wird gesichert …"
                else:
                    message = f"Client {index}/{total}: {host_name} · {repository_name} – Cache wird übertragen …"
                _report(
                    progress, stage="client_cache", message=message, percent=percent,
                    current=index, total=total, bytes_done=int(item.get("bytes_done") or 0),
                    host_name=host_name, repository_name=repository_name,
                )

            client_entries = (
                collect_client_borg_caches(archive, client_progress)
                if progress is not None else collect_client_borg_caches(archive)
            )
            summary = client_cache_summary(client_entries)
            manifest["client_borg_caches"] = client_entries
            manifest["client_borg_cache_target_count"] = summary["target_count"]
            manifest["client_borg_cache_saved_count"] = summary["saved_count"]
            manifest["client_borg_cache_missing_count"] = summary["missing_count"]
            manifest["client_borg_cache_skipped_count"] = summary["skipped_count"]
            manifest["client_borg_cache_warning_count"] = summary["warning_count"]
            manifest["client_borg_cache_source_bytes"] = summary["tar_bytes"]
            manifest["client_borg_security_saved_count"] = summary["security_saved_count"]
            manifest["client_borg_security_missing_count"] = summary["security_missing_count"]
            manifest["client_borg_security_unresolved_count"] = summary["security_unresolved_count"]
            manifest["client_borg_security_source_bytes"] = summary["security_tar_bytes"]
            manifest["includes"].extend(["client_borg_cache", "client_borg_security"])

        _report(progress, stage="finalize_archive", message="Cache-Backup-Archiv wird abgeschlossen …", percent=78.0, current=None, total=None, bytes_done=0)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        archive.writestr("permissions.json", json.dumps(permissions, indent=2, sort_keys=True) + "\n")
    return manifest

def _derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 8:
        raise ValueError("Die Backup-Passphrase muss mindestens 8 Zeichen lang sein")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _encrypt_backup(source_zip: Path, destination: Path, manifest: dict, passphrase: str, progress: ProgressCallback | None = None) -> None:
    if len(passphrase) < 12:
        raise ValueError("Verschlüsselte Backups benötigen eine Passphrase mit mindestens 12 Zeichen")
    if any(character in passphrase for character in "\x00\r\n"):
        raise ValueError("Die Backup-Passphrase muss einzeilig sein")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "format": BACKUP_ENVELOPE_FORMAT,
        "format_version": 2,
        "app_version": manifest.get("app_version"),
        "created_at": manifest.get("created_at"),
        "label": manifest.get("label"),
        "backup_type": backup_type_from_manifest(manifest),
        "content_format": manifest.get("format"),
        "encrypted": True,
        "cipher": "AES-256-GCM-stream",
        "kdf": "scrypt-n32768-r8-p1",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "tag_bytes": 16,
        "borg_cache_included": bool(manifest.get("borg_cache_included")),
        "borg_security_included": bool(manifest.get("borg_security_included")),
        "client_borg_cache_included": bool(manifest.get("client_borg_cache_included")),
        "client_borg_cache_target_count": int(manifest.get("client_borg_cache_target_count") or 0),
        "client_borg_cache_saved_count": int(manifest.get("client_borg_cache_saved_count") or 0),
        "client_borg_cache_missing_count": int(manifest.get("client_borg_cache_missing_count") or 0),
        "client_borg_cache_skipped_count": int(manifest.get("client_borg_cache_skipped_count") or 0),
        "client_borg_cache_warning_count": int(manifest.get("client_borg_cache_warning_count") or 0),
        "client_borg_security_included": bool(manifest.get("client_borg_security_included")),
        "client_borg_security_saved_count": int(manifest.get("client_borg_security_saved_count") or 0),
        "client_borg_security_missing_count": int(manifest.get("client_borg_security_missing_count") or 0),
        "client_borg_security_unresolved_count": int(manifest.get("client_borg_security_unresolved_count") or 0),
        "compression": manifest.get("compression", "deflate-6"),
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    aad = BACKUP_MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
    encryptor = Cipher(algorithms.AES(_derive_backup_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    source_size = max(1, source_zip.stat().st_size)
    processed = 0
    last_reported_percent = -1
    _report(progress, stage="encrypt", message="Backup wird mit AES-256-GCM verschlüsselt …", percent=82.0, bytes_done=0, bytes_total=source_size)
    with source_zip.open("rb") as source, destination.open("wb") as handle:
        handle.write(aad)
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            processed += len(chunk)
            encrypt_percent = 82.0 + (16.0 * processed / source_size)
            whole_percent = int(encrypt_percent)
            if whole_percent != last_reported_percent:
                last_reported_percent = whole_percent
                _report(progress, stage="encrypt", message="Backup wird mit AES-256-GCM verschlüsselt …", percent=min(98.0, encrypt_percent), bytes_done=processed, bytes_total=source_size)
            encrypted = encryptor.update(chunk)
            if encrypted:
                handle.write(encrypted)
        final = encryptor.finalize()
        if final:
            handle.write(final)
        handle.write(encryptor.tag)


def create_full_backup(
    app_version: str,
    label: str = "",
    passphrase: str | None = None,
    *,
    compression: str = "standard",
    progress: ProgressCallback | None = None,
) -> Path:
    if not passphrase:
        raise ValueError("Neue Manager-Backups müssen verschlüsselt werden")
    _report(progress, stage="prepare", message="Manager-Backup wird vorbereitet …", percent=1.0)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    normalized_label = _label(label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIR / f"borgbackup-manager-backup-v{app_version}-{stamp}-{normalized_label}.bbm"
    with NamedTemporaryFile(prefix="bbm-backup-", suffix=".zip", dir=DATA_DIR, delete=False) as temporary:
        plain_zip = Path(temporary.name)
    try:
        manifest = _write_plain_backup(
            plain_zip, app_version, label.strip() or "Manuell",
            compression=compression, progress=progress,
        )
        try:
            _encrypt_backup(plain_zip, destination, manifest, passphrase, progress=progress)
            _validate_backup_file_size(destination)
            os.chmod(destination, 0o600)
            _report(progress, stage="complete", message="Manager-Backup wurde erfolgreich erstellt.", percent=100.0, bytes_done=destination.stat().st_size, bytes_total=destination.stat().st_size)
            return destination
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    finally:
        plain_zip.unlink(missing_ok=True)


def create_cache_backup(
    app_version: str,
    label: str = "",
    passphrase: str | None = None,
    *,
    encrypted: bool = True,
    include_manager_borg_cache: bool = True,
    include_client_borg_cache: bool = True,
    compression: str = "standard",
    progress: ProgressCallback | None = None,
) -> Path:
    """Create a cache-only backup, optionally encrypted.

    Cache metadata is not required to be encrypted for Borg to function, but
    encrypted output is the safer default because Borg caches contain metadata
    about backed-up files and repositories.
    """
    if encrypted and not passphrase:
        raise ValueError("Für ein verschlüsseltes Cache-Backup ist eine Passphrase erforderlich")
    if not encrypted and passphrase:
        raise ValueError("Eine Passphrase ist nur bei aktivierter Cache-Backup-Verschlüsselung zulässig")
    _report(progress, stage="prepare", message="Cache-Backup wird vorbereitet …", percent=1.0)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    normalized_label = _label(label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = ".bbm" if encrypted else ".zip"
    destination = BACKUP_DIR / f"borgbackup-manager-cache-v{app_version}-{stamp}-{normalized_label}{suffix}"
    with NamedTemporaryFile(prefix="bbm-cache-backup-", suffix=".zip", dir=DATA_DIR, delete=False) as temporary:
        plain_zip = Path(temporary.name)
    try:
        manifest = _write_cache_backup(
            plain_zip,
            app_version,
            label.strip() or "Manuell",
            include_manager_borg_cache=include_manager_borg_cache,
            include_client_borg_cache=include_client_borg_cache,
            compression=compression,
            progress=progress,
        )
        try:
            if encrypted:
                _encrypt_backup(plain_zip, destination, manifest, passphrase or "", progress=progress)
            else:
                shutil.copy2(plain_zip, destination)
            _validate_backup_file_size(destination, include_borg_cache=True, include_client_borg_cache=include_client_borg_cache)
            os.chmod(destination, 0o600)
            _report(progress, stage="complete", message="Cache-Backup wurde erfolgreich erstellt.", percent=100.0, bytes_done=destination.stat().st_size, bytes_total=destination.stat().st_size)
            return destination
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    finally:
        plain_zip.unlink(missing_ok=True)


def _backup_file_limit(include_borg_cache: bool, include_client_borg_cache: bool = False) -> int:
    return BACKUP_CACHE_MAX_FILE_BYTES if (include_borg_cache or include_client_borg_cache) else BACKUP_MAX_FILE_BYTES


def _validate_backup_file_size(
    path: Path, *, include_borg_cache: bool = False, include_client_borg_cache: bool = False
) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Backup-Datei kann nicht gelesen werden") from exc
    if size <= 0:
        raise ValueError("Backup-Datei ist leer")
    limit = _backup_file_limit(include_borg_cache, include_client_borg_cache)
    if size > limit:
        raise ValueError(
            f"Backup-Datei überschreitet die zulässige Größe von {limit} Bytes"
        )


def _safe_relative_path(value: str) -> Path:
    if not value or "\x00" in value or "\\" in value or value.startswith(("/", "\\")):
        raise ValueError(f"Unsicherer Backup-Pfad: {value}")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsicherer Backup-Pfad: {value}")
    return path


def _contained_target(destination: Path, relative: Path) -> Path:
    root = destination.resolve()
    target = (root / relative).resolve(strict=False)
    if target == root or root not in target.parents:
        raise ValueError(f"Backup-Pfad verlässt das Wiederherstellungsverzeichnis: {relative.as_posix()}")
    return target


def _read_encrypted_header(path: Path, *, validate_size: bool = True) -> tuple[dict, bytes, int]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Backup-Datei kann nicht gelesen werden") from exc
    if size <= 0:
        raise ValueError("Backup-Datei ist leer")
    with path.open("rb") as handle:
        magic = handle.read(len(BACKUP_MAGIC))
        if magic != BACKUP_MAGIC:
            raise ValueError("Unbekanntes verschlüsseltes Backup-Format")
        raw_length = handle.read(4)
        if len(raw_length) != 4:
            raise ValueError("Backup-Header ist unvollständig")
        header_length = struct.unpack(">I", raw_length)[0]
        if header_length < 32 or header_length > 65_536:
            raise ValueError("Backup-Header hat eine ungültige Größe")
        header_bytes = handle.read(header_length)
        if len(header_bytes) != header_length:
            raise ValueError("Backup-Header ist unvollständig")
    try:
        header = json.loads(header_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Backup-Header ist ungültig") from exc
    if header.get("format") != BACKUP_ENVELOPE_FORMAT:
        raise ValueError("Datei ist kein verschlüsseltes BorgBackup-Manager-Backup")
    _require_supported_backup_version(header)
    if header.get("format_version") != 2 or header.get("cipher") != "AES-256-GCM-stream":
        raise ValueError("Backup verwendet ein nicht mehr unterstütztes Verschlüsselungsformat")
    if validate_size:
        _validate_backup_file_size(
            path,
            include_borg_cache=bool(header.get("borg_cache_included")),
            include_client_borg_cache=bool(header.get("client_borg_cache_included")),
        )
    return header, BACKUP_MAGIC + raw_length + header_bytes, len(BACKUP_MAGIC) + 4 + header_length


def _decrypt_backup(path: Path, destination: Path, passphrase: str | None) -> None:
    if not passphrase:
        raise ValueError("Für dieses Backup ist die Backup-Passphrase erforderlich")
    header, aad, payload_offset = _read_encrypted_header(path)
    try:
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError("Backup-Header enthält ungültige Verschlüsselungsparameter") from exc
    key = _derive_backup_key(passphrase, salt)
    tag_bytes = int(header.get("tag_bytes", 16))
    if tag_bytes != 16:
        raise ValueError("Backup-Header enthält eine ungültige GCM-Tag-Größe")
    file_size = path.stat().st_size
    ciphertext_size = file_size - payload_offset - tag_bytes
    if ciphertext_size <= 0:
        raise ValueError("Verschlüsseltes Backup ist unvollständig")
    with path.open("rb") as source:
        source.seek(file_size - tag_bytes)
        tag = source.read(tag_bytes)
        source.seek(payload_offset)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        remaining = ciphertext_size
        try:
            with destination.open("wb") as handle:
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Verschlüsseltes Backup ist unvollständig")
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    if plaintext:
                        handle.write(plaintext)
                final = decryptor.finalize()
                if final:
                    handle.write(final)
        except InvalidTag as exc:
            destination.unlink(missing_ok=True)
            raise ValueError("Backup-Passphrase ist falsch oder das Backup wurde verändert") from exc
    os.chmod(destination, 0o600)


@contextmanager
def plain_backup_file(path: Path, passphrase: str | None = None):
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            manifest = _read_any_backup_manifest(archive)
        _validate_backup_file_size(
            path,
            include_borg_cache=bool(manifest.get("borg_cache_included") or manifest.get("format") == CACHE_BACKUP_FORMAT),
            include_client_borg_cache=bool(manifest.get("client_borg_cache_included")),
        )
        yield path
        return
    with NamedTemporaryFile(prefix="bbm-decrypted-", suffix=".zip", dir=DATA_DIR, delete=False) as temporary:
        decrypted = Path(temporary.name)
    try:
        _decrypt_backup(path, decrypted, passphrase)
        yield decrypted
    finally:
        decrypted.unlink(missing_ok=True)


def _read_any_backup_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest_info = archive.getinfo("manifest.json")
    except KeyError as exc:
        raise ValueError("Manifest fehlt oder ist ungültig") from exc
    if manifest_info.file_size < 2 or manifest_info.file_size > 1024 * 1024:
        raise ValueError("Manifest hat eine ungültige Größe")
    try:
        manifest = json.loads(archive.read(manifest_info))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest fehlt oder ist ungültig") from exc
    if not isinstance(manifest, dict) or manifest.get("format") not in {BACKUP_FORMAT, CACHE_BACKUP_FORMAT}:
        raise ValueError("Datei ist kein unterstütztes BorgBackup-Manager-Backup")
    _require_supported_backup_version(manifest)
    return manifest


def _read_cache_backup_manifest(archive: zipfile.ZipFile) -> dict:
    manifest = _read_any_backup_manifest(archive)
    if manifest.get("format") != CACHE_BACKUP_FORMAT:
        raise ValueError("Backup ist kein eigenständiges Borg-Cache-Backup")
    return manifest


def _client_cache_entries_from_manifest(manifest: dict) -> list[dict]:
    if not manifest.get("client_borg_cache_included"):
        return []
    raw_entries = manifest.get("client_borg_caches", [])
    if not isinstance(raw_entries, list) or len(raw_entries) > 10000:
        raise ValueError("Client-Cache-Metadaten im Backup sind ungültig")
    entries: list[dict] = []
    seen: set[tuple[int, int]] = set()
    allowed_status = {"saved", "missing", "skipped_disabled"}
    allowed_security_status = {"saved", "missing", "unresolved", "skipped_disabled", ""}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("Client-Cache-Metadaten im Backup sind ungültig")
        try:
            host_id = int(raw.get("host_id"))
            repository_id = int(raw.get("repository_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Client-Cache-Metadaten enthalten ungültige IDs") from exc
        if host_id <= 0 or repository_id <= 0 or isinstance(raw.get("host_id"), bool) or isinstance(raw.get("repository_id"), bool):
            raise ValueError("Client-Cache-Metadaten enthalten ungültige IDs")
        key = (host_id, repository_id)
        if key in seen:
            raise ValueError("Client-Cache-Metadaten enthalten doppelte Geräte-/Repository-Zuordnungen")
        seen.add(key)
        status = str(raw.get("status") or "")
        if status not in allowed_status:
            raise ValueError("Client-Cache-Metadaten enthalten einen ungültigen Status")
        security_status = str(raw.get("security_status") or "")
        if security_status not in allowed_security_status:
            raise ValueError("Client-Sicherheitsstatus-Metadaten enthalten einen ungültigen Status")
        borg_repository_id = str(raw.get("borg_repository_id") or "").strip().lower() or None
        if borg_repository_id is not None and (
            len(borg_repository_id) != 64 or any(character not in "0123456789abcdef" for character in borg_repository_id)
        ):
            raise ValueError("Client-Sicherheitsstatus-Metadaten enthalten eine ungültige Borg-Repository-ID")
        item = {
            "host_id": host_id,
            "host_name": str(raw.get("host_name") or f"#{host_id}"),
            "repository_id": repository_id,
            "repository_name": str(raw.get("repository_name") or f"#{repository_id}"),
            "borg_version": raw.get("borg_version"),
            "cache_path": str(raw.get("cache_path") or f"$HOME/.cache/borgbackup-manager/repository-{repository_id}"),
            "security_base_path": str(raw.get("security_base_path") or "$HOME/.config/borg/security"),
            "collected_at": raw.get("collected_at"),
            "status": status,
            "reason": str(raw.get("reason") or "") or None,
            "tar_bytes": int(raw.get("tar_bytes") or 0),
            "security_status": security_status,
            "security_reason": str(raw.get("security_reason") or "") or None,
            "borg_repository_id": borg_repository_id,
            "security_tar_bytes": int(raw.get("security_tar_bytes") or 0),
        }
        if status == "saved":
            expected = f"data/client-borg-cache/host-{host_id}/repository-{repository_id}.tar"
            archive_path = str(raw.get("archive_path") or "")
            if archive_path != expected:
                raise ValueError("Client-Cache-Metadaten enthalten einen ungültigen Archivpfad")
            item["archive_path"] = archive_path
        if security_status == "saved":
            if borg_repository_id is None:
                raise ValueError("Gesicherter Client-Sicherheitsstatus enthält keine Borg-Repository-ID")
            expected_security = f"data/client-borg-security/host-{host_id}/repository-{repository_id}.tar"
            security_archive_path = str(raw.get("security_archive_path") or "")
            if security_archive_path != expected_security:
                raise ValueError("Client-Sicherheitsstatus-Metadaten enthalten einen ungültigen Archivpfad")
            item["security_archive_path"] = security_archive_path
            item["security_path"] = str(
                raw.get("security_path") or f"$HOME/.config/borg/security/{borg_repository_id}"
            )
        entries.append(item)
    return entries


def client_borg_cache_inventory(path: Path, passphrase: str | None = None) -> dict:
    """Authenticate a current cache backup and return its per-device inventory."""
    with plain_backup_file(path, passphrase) as plain:
        with zipfile.ZipFile(plain) as archive:
            manifest = _read_cache_backup_manifest(archive)
            entries = _client_cache_entries_from_manifest(manifest)
    return {
        "backup_version": manifest.get("app_version"),
        "created_at": manifest.get("created_at"),
        "included": bool(manifest.get("client_borg_cache_included")),
        "security_included": bool(manifest.get("client_borg_security_included")),
        "target_count": int(manifest.get("client_borg_cache_target_count") or len(entries)),
        "saved_count": sum(1 for item in entries if item["status"] == "saved"),
        "missing_count": sum(1 for item in entries if item["status"] == "missing"),
        "skipped_count": sum(1 for item in entries if item["status"].startswith("skipped_")),
        "warning_count": sum(1 for item in entries if item["status"] == "warning"),
        "security_saved_count": sum(1 for item in entries if item.get("security_status") == "saved"),
        "security_missing_count": sum(1 for item in entries if item.get("security_status") == "missing"),
        "security_unresolved_count": sum(1 for item in entries if item.get("security_status") == "unresolved"),
        "entries": entries,
    }


def restore_client_borg_cache_from_backup(
    path: Path, passphrase: str | None, host, repository_id: int
) -> dict:
    """Restore one saved client cache and add missing Borg security state when available."""
    repository_id = int(repository_id)
    with plain_backup_file(path, passphrase) as plain:
        with zipfile.ZipFile(plain) as archive:
            manifest = _read_cache_backup_manifest(archive)
            entries = _client_cache_entries_from_manifest(manifest)
            entry = next(
                (item for item in entries if item["host_id"] == int(host.id) and item["repository_id"] == repository_id),
                None,
            )
            if not entry:
                raise ValueError("Backup enthält keinen Client-Cache für dieses Gerät und Repository")
            if entry["status"] != "saved":
                raise ValueError(entry.get("reason") or "Für diese Zuordnung wurde kein Client-Cache gesichert")
            try:
                info = archive.getinfo(entry["archive_path"])
            except KeyError as exc:
                raise ValueError("Gesicherter Client-Cache fehlt im Backup") from exc
            if info.is_dir() or info.file_size <= 0 or info.file_size > BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Gesicherter Client-Cache hat eine ungültige Größe")
            from app.client_cache import restore_client_borg_cache_stream, restore_client_borg_security_stream
            with archive.open(info, "r") as source:
                result = restore_client_borg_cache_stream(host, repository_id, source)

            security_result = None
            if entry.get("security_status") == "saved":
                try:
                    security_info = archive.getinfo(entry["security_archive_path"])
                except KeyError as exc:
                    raise ValueError("Gesicherter Client-Borg-Sicherheitsstatus fehlt im Backup") from exc
                if security_info.is_dir() or security_info.file_size <= 0 or security_info.file_size > BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Gesicherter Client-Borg-Sicherheitsstatus hat eine ungültige Größe")
                with archive.open(security_info, "r") as security_source:
                    security_result = restore_client_borg_security_stream(
                        host, str(entry["borg_repository_id"]), security_source
                    )
    result.update({
        "host_name": entry["host_name"],
        "repository_name": entry["repository_name"],
        "backup_version": manifest.get("app_version"),
        "collected_at": entry.get("collected_at"),
        "security_status": entry.get("security_status") or None,
        "security_restore": security_result,
    })
    return result

def restore_manager_borg_cache_from_backup(path: Path, passphrase: str | None = None) -> dict:
    """Restore the manager-side Borg cache/security state from a cache backup.

    Existing directories are renamed and retained as a local safety copy. The
    caller must ensure there are no queued/running Borg operations.
    """
    staging_root = DATA_DIR / "restore-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    os.chmod(staging_root, 0o700)
    staging = Path(mkdtemp(prefix="cache-restore-", dir=staging_root))
    try:
        with plain_backup_file(path, passphrase) as plain:
            with zipfile.ZipFile(plain) as archive:
                manifest = _read_cache_backup_manifest(archive)
                if not manifest.get("borg_cache_included"):
                    raise ValueError("Cache-Backup enthält keinen Manager-Borg-Cache")
                _safe_extract(archive, staging, skip_extract_prefixes=("data/client-borg-cache/", "data/client-borg-security/"))

        source_root = staging / "data"
        incoming_cache = source_root / "borg-cache"
        incoming_security = source_root / "borg-security"
        # Empty cache trees have no ZIP member of their own; represent them as
        # empty directories so a deliberate empty-state restore still works.
        incoming_cache.mkdir(parents=True, exist_ok=True)
        incoming_security.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        pairs = [
            (incoming_cache, MANAGER_BORG_CACHE_DIR, DATA_DIR / f"borg-cache.pre-bbm-restore-{stamp}"),
            (incoming_security, MANAGER_BORG_SECURITY_DIR, DATA_DIR / f"borg-security.pre-bbm-restore-{stamp}"),
        ]
        moved_previous: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        try:
            for incoming, target, previous in pairs:
                if previous.exists():
                    if previous.is_dir():
                        shutil.rmtree(previous)
                    else:
                        previous.unlink()
                if target.exists():
                    target.replace(previous)
                    moved_previous.append((previous, target))
                target.parent.mkdir(parents=True, exist_ok=True)
                incoming.replace(target)
                installed.append(target)
        except Exception:
            for target in reversed(installed):
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
            for previous, target in reversed(moved_previous):
                if previous.exists() and not target.exists():
                    previous.replace(target)
            raise

        return {
            "status": "restored",
            "backup_version": manifest.get("app_version"),
            "created_at": manifest.get("created_at"),
            "previous_cache": str(pairs[0][2]) if pairs[0][2].exists() else None,
            "previous_security": str(pairs[1][2]) if pairs[1][2].exists() else None,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _safe_extract(
    archive: zipfile.ZipFile, destination: Path, *, skip_extract_prefixes: tuple[str, ...] = ()
) -> dict:
    manifest = _read_any_backup_manifest(archive)
    includes_cache = bool(manifest.get("borg_cache_included") or manifest.get("client_borg_cache_included"))
    max_entries = BACKUP_CACHE_MAX_ENTRIES if includes_cache else BACKUP_MAX_ENTRIES
    max_uncompressed = BACKUP_CACHE_MAX_UNCOMPRESSED_BYTES if includes_cache else BACKUP_MAX_UNCOMPRESSED_BYTES
    max_ratio = BACKUP_CACHE_MAX_COMPRESSION_RATIO if includes_cache else BACKUP_MAX_COMPRESSION_RATIO

    entries = archive.infolist()
    if len(entries) > max_entries:
        raise ValueError(f"Backup enthält mehr als {max_entries} Einträge")
    names: set[str] = set()
    uncompressed_total = 0
    compressed_total = 0
    for item in entries:
        relative = _safe_relative_path(item.filename.rstrip("/") if item.is_dir() else item.filename)
        normalized = relative.as_posix()
        if normalized in names:
            raise ValueError(f"Doppelter Eintrag im Backup: {normalized}")
        names.add(normalized)
        _contained_target(destination, relative)
        mode = (item.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ValueError(f"Symbolischer Link im Backup ist nicht erlaubt: {item.filename}")
        if item.file_size < 0 or item.compress_size < 0:
            raise ValueError(f"Ungültige Größenangabe im Backup: {item.filename}")
        if item.file_size and item.file_size / max(1, item.compress_size) > max_ratio:
            raise ValueError(f"Backup-Eintrag weist ein unzulässig hohes Kompressionsverhältnis auf: {item.filename}")
        uncompressed_total += int(item.file_size)
        compressed_total += int(item.compress_size)
        if uncompressed_total > max_uncompressed:
            raise ValueError(
                f"Entpackter Backup-Inhalt überschreitet {max_uncompressed} Bytes"
            )
    if uncompressed_total and uncompressed_total / max(1, compressed_total) > max_ratio:
        raise ValueError("Backup weist ein unzulässig hohes Kompressionsverhältnis auf")
    for item in entries:
        normalized = _safe_relative_path(item.filename.rstrip("/") if item.is_dir() else item.filename).as_posix()
        if any(normalized.startswith(prefix) for prefix in skip_extract_prefixes):
            continue
        archive.extract(item, destination)
    permissions_path = destination / "permissions.json"
    if permissions_path.is_file():
        try:
            permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Berechtigungsmanifest ist ungültig") from exc
        if not isinstance(permissions, dict) or len(permissions) > max_entries:
            raise ValueError("Berechtigungsmanifest enthält ungültig viele Einträge")
        for relative_text, mode_value in permissions.items():
            if (
                not isinstance(relative_text, str)
                or isinstance(mode_value, bool)
                or not isinstance(mode_value, int)
                or mode_value < 0
                or mode_value > 0o7777
            ):
                raise ValueError("Berechtigungsmanifest enthält ungültige Werte")
            relative = _safe_relative_path(relative_text)
            target = _contained_target(destination, relative)
            if target.is_file() and not target.is_symlink():
                os.chmod(target, int(mode_value) & 0o777)
    return manifest


def _parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def prepare_full_backup_restore(path: Path, passphrase: str | None = None) -> tuple[Path, dict]:
    staging_root = DATA_DIR / "restore-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    os.chmod(staging_root, 0o700)
    staging = Path(mkdtemp(prefix="restore-", dir=staging_root))
    try:
        with plain_backup_file(path, passphrase) as plain:
            with zipfile.ZipFile(plain) as archive:
                manifest = _safe_extract(archive, staging, skip_extract_prefixes=("data/client-borg-cache/", "data/client-borg-security/"))
                if manifest.get("format") != BACKUP_FORMAT:
                    raise ValueError("Cache-Backup kann nicht als Manager-Backup wiederhergestellt werden")
        migration_path = staging / "migration.env"
        if not migration_path.is_file():
            raise ValueError("Backup enthält keine Migrationsumgebung")
        _parse_env(migration_path)
        if not (staging / "data" / "manager.db").is_file():
            raise ValueError("Backup enthält keine Manager-Datenbank")
        return staging, manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def apply_prepared_restore(staging: Path) -> None:
    source = staging / "data"
    if not source.is_dir():
        raise ValueError("Vorbereitete Wiederherstellung enthält keine Daten")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for component in RESTORE_COMPONENTS:
        incoming = source / component
        target = DATA_DIR / component
        if not incoming.exists():
            # Backups created before the notification center must not retain a
            # newer installation's channel configuration after a rollback.
            # Notification secrets are already replaced with security.db.
            if component == "notifications.json":
                target.unlink(missing_ok=True)
            continue
        temporary_target = DATA_DIR / f".{component}.restore-new"
        if temporary_target.exists():
            if temporary_target.is_dir():
                shutil.rmtree(temporary_target)
            else:
                temporary_target.unlink()
        if incoming.is_dir():
            shutil.copytree(incoming, temporary_target, copy_function=shutil.copy2)
        else:
            shutil.copy2(incoming, temporary_target)
        if component == "manager.db":
            Path(str(target) + "-wal").unlink(missing_ok=True)
            Path(str(target) + "-shm").unlink(missing_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        temporary_target.replace(target)
    shutil.rmtree(staging, ignore_errors=True)


def validate_uploaded_backup(path: Path, name: str) -> dict:
    """Validate an uploaded manager/cache backup without modifying persistent state."""
    if not BACKUP_NAME.fullmatch(name):
        raise ValueError("Ungültiger Backup-Dateiname")
    suffix = Path(name).suffix.lower()
    if suffix == ".bbm":
        header, _aad, payload_offset = _read_encrypted_header(path)
        supported_ciphers = {"AES-256-GCM", "AES-256-GCM-stream"}
        if header.get("cipher") not in supported_ciphers or header.get("kdf") != "scrypt-n32768-r8-p1":
            raise ValueError("Backup verwendet nicht unterstützte Verschlüsselungsparameter")
        try:
            salt = base64.b64decode(header["salt"], validate=True)
            nonce = base64.b64decode(header["nonce"], validate=True)
        except (KeyError, ValueError) as exc:
            raise ValueError("Backup-Header enthält ungültige Verschlüsselungsparameter") from exc
        if len(salt) != 16 or len(nonce) != 12 or path.stat().st_size <= payload_offset + 16:
            raise ValueError("Verschlüsseltes Backup ist unvollständig")
        backup_type = str(header.get("backup_type") or ("cache" if CACHE_BACKUP_NAME.fullmatch(name) else "manager"))
        if backup_type not in {"manager", "cache"}:
            raise ValueError("Backup-Header enthält einen unbekannten Backup-Typ")
        if backup_type == "cache" and not CACHE_BACKUP_NAME.fullmatch(name):
            raise ValueError("Cache-Backup hat keinen gültigen Cache-Backup-Dateinamen")
        if backup_type == "manager" and not MANAGER_BACKUP_NAME.fullmatch(name):
            raise ValueError("Manager-Backup hat keinen gültigen Manager-Backup-Dateinamen")
        header["backup_type"] = backup_type
        return {"encrypted": True, "backup_type": backup_type, "manifest": header}
    if suffix != ".zip":
        raise ValueError("Nur .bbm- und .zip-Backups werden unterstützt")
    staging = Path(mkdtemp(prefix="bbm-upload-check-", dir=DATA_DIR))
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _read_any_backup_manifest(archive)
            backup_type = backup_type_from_manifest(manifest)
            if backup_type == "cache" and not CACHE_BACKUP_NAME.fullmatch(name):
                raise ValueError("Cache-Backup hat keinen gültigen Cache-Backup-Dateinamen")
            if backup_type == "manager" and not MANAGER_BACKUP_NAME.fullmatch(name):
                raise ValueError("Manager-Backup hat keinen gültigen Manager-Backup-Dateinamen")
            _validate_backup_file_size(
                path,
                include_borg_cache=bool(manifest.get("borg_cache_included") or backup_type == "cache"),
                include_client_borg_cache=bool(manifest.get("client_borg_cache_included")),
            )
            # Validate every archive entry but do not duplicate potentially
            # multi-GiB cache payloads into the upload validation directory.
            manifest = _safe_extract(archive, staging, skip_extract_prefixes=("data/",))
        return {"encrypted": False, "backup_type": backup_type, "manifest": manifest}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def store_uploaded_backup(path: Path, name: str) -> dict:
    """Atomically add one validated uploaded backup without overwriting files."""
    validation = validate_uploaded_backup(path, name)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    destination = BACKUP_DIR / name
    try:
        os.link(path, destination)
    except FileExistsError as exc:
        raise FileExistsError("Ein Manager-Backup mit diesem Dateinamen ist bereits vorhanden") from exc
    os.chmod(destination, 0o600)
    path.unlink(missing_ok=True)
    stat_result = destination.stat()
    return {
        "name": destination.name,
        "size_bytes": stat_result.st_size,
        "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat(),
        "encrypted": validation["encrypted"],
        "backup_type": validation.get("backup_type") or backup_type_from_manifest(validation["manifest"]),
        "manifest": validation["manifest"],
    }


def list_full_backups() -> list[dict]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    paths = list(BACKUP_DIR.glob("*.zip")) + list(BACKUP_DIR.glob("*.bbm"))
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True):
        manifest: dict = {}
        encrypted = path.suffix == ".bbm"
        try:
            if encrypted:
                manifest, _aad, _offset = _read_encrypted_header(path)
            else:
                with zipfile.ZipFile(path) as archive:
                    manifest = _read_any_backup_manifest(archive)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            pass
        stat_result = path.stat()
        backup_type = str(manifest.get("backup_type") or ("cache" if CACHE_BACKUP_NAME.fullmatch(path.name) else "manager"))
        items.append({
            "name": path.name,
            "size_bytes": stat_result.st_size,
            "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat(),
            "encrypted": encrypted,
            "backup_type": backup_type,
            "manifest": manifest,
        })
    return items


def backup_path(name: str) -> Path:
    if not BACKUP_NAME.fullmatch(name):
        raise ValueError("Ungültiger Backup-Dateiname")
    path = BACKUP_DIR / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path
