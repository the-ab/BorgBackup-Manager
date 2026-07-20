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
from tempfile import NamedTemporaryFile, mkdtemp

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.config import (
    BACKUP_DIR,
    BACKUP_MAX_COMPRESSION_RATIO,
    BACKUP_MAX_ENTRIES,
    BACKUP_MAX_FILE_BYTES,
    BACKUP_MAX_UNCOMPRESSED_BYTES,
    DATA_DIR,
    DATABASE_URL,
    SECURITY_DATABASE_PATH,
    SETTINGS_PATH,
    NOTIFICATION_SETTINGS_PATH,
)


BACKUP_FORMAT = "borgbackup-manager-full-backup"
BACKUP_ENVELOPE_FORMAT = "borgbackup-manager-encrypted-backup"
BACKUP_MAGIC = b"BBM-BACKUP-1\n"
BACKUP_NAME = re.compile(
    r"^borgbackup-manager-backup-v[0-9A-Za-z.+-]+-[0-9]{8}-[0-9]{6}-[a-zA-Z0-9_-]+\.(?:zip|bbm)$"
)
RESTORE_COMPONENTS = ("manager.db", "settings.json", "notifications.json", "ssh", "repository-ssh", "repository-keys", "tls", "security")


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


def _add_tree(archive: zipfile.ZipFile, source: Path, prefix: str, permissions: dict[str, int]) -> int:
    count = 0
    if not source.is_dir():
        return count
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        arcname = f"data/{prefix}/{path.relative_to(source).as_posix()}"
        archive.write(path, arcname)
        permissions[arcname] = stat.S_IMODE(path.stat().st_mode) & 0o777
        count += 1
    return count


def _migration_env() -> str:
    keys = (
        "TZ", "BBM_HTTPS_PORT", "BBM_TLS_HOSTS", "BBM_SESSION_TTL_SECONDS",
        "BBM_SESSION_IDLE_TIMEOUT_SECONDS", "BBM_SESSION_COOKIE_NAME", "BBM_SESSION_COOKIE_SECURE",
        "BBM_TRUSTED_PROXY_CIDRS", "BBM_LOGIN_RATE_WINDOW_SECONDS", "BBM_LOGIN_RATE_BLOCK_SECONDS",
        "BBM_LOGIN_RATE_MAX_PER_IP", "BBM_LOGIN_RATE_MAX_PER_IP_USER",
        "BBM_SECURITY_EVENT_RETENTION_DAYS", "BBM_SECURITY_EVENT_MAX_ROWS",
        "BBM_BACKUP_MAX_FILE_BYTES", "BBM_BACKUP_MAX_UNCOMPRESSED_BYTES",
        "BBM_BACKUP_MAX_ENTRIES", "BBM_BACKUP_MAX_COMPRESSION_RATIO",
        "BBM_COMMAND_TIMEOUT", "BBM_APPEARANCE",
        "BBM_REPOSITORY_SIZE_AFTER_RUN", "BBM_REPOSITORY_PUBLIC_HOST",
        "BBM_REPOSITORY_SSH_PORT", "BBM_BORG_UID", "BBM_BORG_GID",
        "BBM_STORAGE_GUARD_ENABLED", "BBM_STORAGE_GUARD_THRESHOLD_PERCENT",
        "BBM_HEALTH_REQUIRE_SSHD", "BBM_LOG_MAX_BYTES", "BBM_LOG_ROTATIONS", "BBM_DEBUG_LOG_LEVEL",
        "BBM_DATA_PATH", "BBM_REPOSITORY_PATH",
    )
    lines = []
    for key in keys:
        value = os.getenv(key, "")
        if "\n" in value or "\r" in value:
            raise ValueError(f"Umgebungswert {key} enthält einen Zeilenumbruch")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def _write_plain_backup(destination: Path, app_version: str, label: str) -> dict:
    with NamedTemporaryFile(prefix="bbm-db-", suffix=".sqlite3", dir=DATA_DIR, delete=False) as temporary:
        snapshot = Path(temporary.name)
    try:
        _sqlite_snapshot(snapshot)
        permissions: dict[str, int] = {}
        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": 3,
            "app_version": app_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "encrypted": False,
            "repository_data_included": False,
            "run_logs_included": False,
            "includes": ["database", "security_database", "master_key", "settings", "notification_settings", "migration_environment"],
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
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
                        # Browser sessions are ephemeral credentials and must
                        # never be revived by restoring an older manager backup.
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
            archive.writestr("permissions.json", json.dumps(permissions, indent=2, sort_keys=True) + "\n")
        return manifest
    finally:
        snapshot.unlink(missing_ok=True)


def _derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 8:
        raise ValueError("Die Backup-Passphrase muss mindestens 8 Zeichen lang sein")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _encrypt_backup(source_zip: Path, destination: Path, manifest: dict, passphrase: str) -> None:
    if len(passphrase) < 12:
        raise ValueError("Neue Manager-Backups benötigen eine Passphrase mit mindestens 12 Zeichen")
    if any(character in passphrase for character in "\x00\r\n"):
        raise ValueError("Die Backup-Passphrase muss einzeilig sein")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "format": BACKUP_ENVELOPE_FORMAT,
        "format_version": 1,
        "app_version": manifest.get("app_version"),
        "created_at": manifest.get("created_at"),
        "label": manifest.get("label"),
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt-n32768-r8-p1",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    aad = BACKUP_MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
    ciphertext = AESGCM(_derive_backup_key(passphrase, salt)).encrypt(nonce, source_zip.read_bytes(), aad)
    with destination.open("wb") as handle:
        handle.write(aad)
        handle.write(ciphertext)


def create_full_backup(app_version: str, label: str = "", passphrase: str | None = None) -> Path:
    if not passphrase:
        raise ValueError("Neue Manager-Backups müssen verschlüsselt werden")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    normalized_label = _label(label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIR / f"borgbackup-manager-backup-v{app_version}-{stamp}-{normalized_label}.bbm"
    with NamedTemporaryFile(prefix="bbm-backup-", suffix=".zip", dir=DATA_DIR, delete=False) as temporary:
        plain_zip = Path(temporary.name)
    try:
        manifest = _write_plain_backup(plain_zip, app_version, label.strip() or "Manuell")
        _encrypt_backup(plain_zip, destination, manifest, passphrase)
        os.chmod(destination, 0o600)
        return destination
    finally:
        plain_zip.unlink(missing_ok=True)


def _validate_backup_file_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Backup-Datei kann nicht gelesen werden") from exc
    if size <= 0:
        raise ValueError("Backup-Datei ist leer")
    if size > BACKUP_MAX_FILE_BYTES:
        raise ValueError(
            f"Backup-Datei überschreitet die zulässige Größe von {BACKUP_MAX_FILE_BYTES} Bytes"
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


def _read_encrypted_header(path: Path) -> tuple[dict, bytes, int]:
    _validate_backup_file_size(path)
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
    return header, BACKUP_MAGIC + raw_length + header_bytes, len(BACKUP_MAGIC) + 4 + header_length


def _decrypt_backup(path: Path, destination: Path, passphrase: str | None) -> None:
    _validate_backup_file_size(path)
    if not passphrase:
        raise ValueError("Für dieses Backup ist die Backup-Passphrase erforderlich")
    header, aad, payload_offset = _read_encrypted_header(path)
    try:
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError("Backup-Header enthält ungültige Verschlüsselungsparameter") from exc
    ciphertext = path.read_bytes()[payload_offset:]
    try:
        plaintext = AESGCM(_derive_backup_key(passphrase, salt)).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise ValueError("Backup-Passphrase ist falsch oder das Backup wurde verändert") from exc
    destination.write_bytes(plaintext)
    os.chmod(destination, 0o600)


@contextmanager
def plain_backup_file(path: Path, passphrase: str | None = None):
    _validate_backup_file_size(path)
    if path.suffix == ".zip":
        yield path
        return
    with NamedTemporaryFile(prefix="bbm-decrypted-", suffix=".zip", dir=DATA_DIR, delete=False) as temporary:
        decrypted = Path(temporary.name)
    try:
        _decrypt_backup(path, decrypted, passphrase)
        yield decrypted
    finally:
        decrypted.unlink(missing_ok=True)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> dict:
    entries = archive.infolist()
    if len(entries) > BACKUP_MAX_ENTRIES:
        raise ValueError(f"Backup enthält mehr als {BACKUP_MAX_ENTRIES} Einträge")
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
        if item.file_size and item.file_size / max(1, item.compress_size) > BACKUP_MAX_COMPRESSION_RATIO:
            raise ValueError(f"Backup-Eintrag weist ein unzulässig hohes Kompressionsverhältnis auf: {item.filename}")
        uncompressed_total += int(item.file_size)
        compressed_total += int(item.compress_size)
        if uncompressed_total > BACKUP_MAX_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"Entpackter Backup-Inhalt überschreitet {BACKUP_MAX_UNCOMPRESSED_BYTES} Bytes"
            )
    if uncompressed_total and uncompressed_total / max(1, compressed_total) > BACKUP_MAX_COMPRESSION_RATIO:
        raise ValueError("Backup weist ein unzulässig hohes Kompressionsverhältnis auf")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest fehlt oder ist ungültig") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("Datei ist kein BorgBackup-Manager-Vollbackup")
    archive.extractall(destination)
    permissions_path = destination / "permissions.json"
    if permissions_path.is_file():
        try:
            permissions = json.loads(permissions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Berechtigungsmanifest ist ungültig") from exc
        if not isinstance(permissions, dict) or len(permissions) > BACKUP_MAX_ENTRIES:
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
                manifest = _safe_extract(archive, staging)
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
    """Validate an uploaded Manager backup without modifying persistent state."""
    if not BACKUP_NAME.fullmatch(name):
        raise ValueError("Ungültiger Backup-Dateiname")
    _validate_backup_file_size(path)
    suffix = Path(name).suffix.lower()
    if suffix == ".bbm":
        header, _aad, payload_offset = _read_encrypted_header(path)
        if header.get("cipher") != "AES-256-GCM" or header.get("kdf") != "scrypt-n32768-r8-p1":
            raise ValueError("Backup verwendet nicht unterstützte Verschlüsselungsparameter")
        try:
            salt = base64.b64decode(header["salt"], validate=True)
            nonce = base64.b64decode(header["nonce"], validate=True)
        except (KeyError, ValueError) as exc:
            raise ValueError("Backup-Header enthält ungültige Verschlüsselungsparameter") from exc
        if len(salt) != 16 or len(nonce) != 12 or path.stat().st_size <= payload_offset + 16:
            raise ValueError("Verschlüsseltes Backup ist unvollständig")
        return {"encrypted": True, "manifest": header}
    if suffix != ".zip":
        raise ValueError("Nur .bbm- und historische .zip-Manager-Backups werden unterstützt")
    staging = Path(mkdtemp(prefix="bbm-upload-check-", dir=DATA_DIR))
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _safe_extract(archive, staging)
        return {"encrypted": False, "manifest": manifest}
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
                    manifest = json.loads(archive.read("manifest.json"))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            pass
        stat_result = path.stat()
        items.append({
            "name": path.name,
            "size_bytes": stat_result.st_size,
            "modified_at": datetime.fromtimestamp(stat_result.st_mtime, timezone.utc).isoformat(),
            "encrypted": encrypted,
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
