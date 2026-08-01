from __future__ import annotations

import base64
import os
import signal
import subprocess
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from sqlalchemy import select

from app.config import COMMAND_TIMEOUT
from app.database import SessionLocal
from app.models import Host, Job, Repository, Run
from app.runner import (
    Command,
    client_borg_cache_export_command,
    client_borg_cache_restore_command,
    client_borg_security_export_command,
    client_borg_security_restore_command,
)


CLIENT_CACHE_ARCHIVE_ROOT = "data/client-borg-cache"
CLIENT_SECURITY_ARCHIVE_ROOT = "data/client-borg-security"


def _safe_error_text(value: str, limit: int = 4000) -> str:
    text = (value or "").replace("\x00", "").strip()
    return text[-limit:] if text else "Unbekannter SSH-/Tar-Fehler"


@contextmanager
def _materialized_command(command: Command) -> Iterator[list[str]]:
    """Materialize the controller key/known-hosts placeholders for streaming I/O."""
    argv = list(command.argv)
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        if command.temp_files:
            temporary_directory = tempfile.TemporaryDirectory(prefix="bbm-client-cache-")
            root = Path(temporary_directory.name)
            replacements: dict[str, str] = {}
            for index, (placeholder, content) in enumerate(command.temp_files.items(), start=1):
                path = root / f"secret-{index}"
                path.write_text(content, encoding="utf-8")
                os.chmod(path, 0o600)
                replacements[placeholder] = str(path)
            resolved: list[str] = []
            for argument in argv:
                for placeholder, path in replacements.items():
                    argument = argument.replace(placeholder, path)
                resolved.append(argument)
            argv = resolved
        yield argv
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


def _start_timeout(process: subprocess.Popen[bytes], timeout_seconds: int) -> tuple[threading.Timer, threading.Event]:
    timed_out = threading.Event()

    def expire() -> None:
        if process.poll() is None:
            timed_out.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    process.kill()
                except OSError:
                    pass

    timer = threading.Timer(max(5, int(timeout_seconds)), expire)
    timer.daemon = True
    timer.start()
    return timer, timed_out


def _target_rows() -> list[tuple[Host, Repository]]:
    """Return unique device/repository pairs that can own a BBM client cache."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Job, Host, Repository)
            .join(Host, Job.host_id == Host.id)
            .join(Repository, Job.repository_id == Repository.id)
            .order_by(Host.name, Host.id, Repository.name, Repository.id, Job.id)
        ).all()
        result: list[tuple[Host, Repository]] = []
        seen: set[tuple[int, int]] = set()
        for _job, host, repository in rows:
            key = (int(host.id), int(repository.id))
            if key in seen:
                continue
            seen.add(key)
            # Scalar attributes used by the streaming helpers are already loaded;
            # closing the session detaches the rows without expiring them.
            result.append((host, repository))
        return result


def _base_metadata(host: Host, repository: Repository) -> dict:
    return {
        "host_id": int(host.id),
        "host_name": str(host.name),
        "repository_id": int(repository.id),
        "repository_name": str(repository.name),
        "borg_version": host.borg_version,
        "cache_path": f"$HOME/.cache/borgbackup-manager/repository-{int(repository.id)}",
        "security_base_path": "$HOME/.config/borg/security",
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def _stream_one_cache(archive: zipfile.ZipFile, host: Host, repository: Repository, arcname: str, progress: Callable[[int], None] | None = None) -> tuple[str, int]:
    command = client_borg_cache_export_command(host, int(repository.id))
    timeout = command.timeout_seconds or COMMAND_TIMEOUT
    with _materialized_command(command) as argv, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            env={**os.environ, **command.env} if command.env else None,
            start_new_session=True,
        )
        timer, timed_out = _start_timeout(process, timeout)
        try:
            if process.stdout is None:
                raise ValueError("SSH-Prozess liefert keinen Client-Cache-Datenstrom")
            protocol = process.stdout.readline(256).decode("utf-8", errors="replace").strip()
            status = process.stdout.readline(256).decode("utf-8", errors="replace").strip()
            if protocol != "BBM_CLIENT_CACHE_V1" or status not in {"PRESENT", "MISSING"}:
                process.kill()
                process.wait()
                stderr_file.seek(0)
                detail = _safe_error_text(stderr_file.read().decode("utf-8", errors="replace"))
                raise ValueError(f"Ungültige Antwort beim Lesen des Client-Caches: {detail}")
            transferred = 0
            if status == "PRESENT":
                with archive.open(arcname, "w", force_zip64=True) as destination:
                    while True:
                        chunk = process.stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)
                        transferred += len(chunk)
                        if progress is not None:
                            progress(transferred)
            else:
                # Drain any unexpected trailing output before waiting for ssh.
                process.stdout.read()
            returncode = process.wait()
        finally:
            timer.cancel()
        stderr_file.seek(0)
        error = stderr_file.read().decode("utf-8", errors="replace")
        if timed_out.is_set():
            raise ValueError(f"Client-Cache-Übertragung hat das Zeitlimit von {timeout} Sekunden überschritten")
        if returncode != 0:
            raise ValueError(f"Client-Cache-Übertragung fehlgeschlagen (rc {returncode}): {_safe_error_text(error)}")
        return status.lower(), transferred


def _stream_one_security(
    archive: zipfile.ZipFile,
    host: Host,
    repository: Repository,
    arcname: str,
    progress: Callable[[int], None] | None = None,
) -> tuple[str, str | None, int]:
    """Stream the Borg 1.x security state for one assigned client repository."""
    command = client_borg_security_export_command(host, int(repository.id), str(repository.location))
    timeout = command.timeout_seconds or COMMAND_TIMEOUT
    with _materialized_command(command) as argv, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            env={**os.environ, **command.env} if command.env else None,
            start_new_session=True,
        )
        timer, timed_out = _start_timeout(process, timeout)
        try:
            if process.stdout is None:
                raise ValueError("SSH-Prozess liefert keinen Client-Sicherheitsstatus-Datenstrom")
            protocol = process.stdout.readline(256).decode("utf-8", errors="replace").strip()
            status = process.stdout.readline(256).decode("utf-8", errors="replace").strip()
            borg_repository_id = process.stdout.readline(256).decode("utf-8", errors="replace").strip().lower()
            if protocol != "BBM_CLIENT_SECURITY_V1" or status not in {"PRESENT", "MISSING", "UNRESOLVED", "ERROR"}:
                process.kill()
                process.wait()
                stderr_file.seek(0)
                detail = _safe_error_text(stderr_file.read().decode("utf-8", errors="replace"))
                raise ValueError(f"Ungültige Antwort beim Lesen des Client-Borg-Sicherheitsstatus: {detail}")
            if borg_repository_id == "-":
                borg_repository_id = ""
            if borg_repository_id and (
                len(borg_repository_id) != 64
                or any(character not in "0123456789abcdef" for character in borg_repository_id)
            ):
                process.kill()
                process.wait()
                raise ValueError("Client meldet eine ungültige Borg-Repository-ID für den Sicherheitsstatus")
            transferred = 0
            if status == "PRESENT":
                if not borg_repository_id:
                    process.kill()
                    process.wait()
                    raise ValueError("Client-Sicherheitsstatus enthält keine Borg-Repository-ID")
                with archive.open(arcname, "w", force_zip64=True) as destination:
                    while True:
                        chunk = process.stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)
                        transferred += len(chunk)
                        if progress is not None:
                            progress(transferred)
            else:
                process.stdout.read()
            returncode = process.wait()
        finally:
            timer.cancel()
        stderr_file.seek(0)
        error = stderr_file.read().decode("utf-8", errors="replace")
        if timed_out.is_set():
            raise ValueError(f"Client-Sicherheitsstatus-Übertragung hat das Zeitlimit von {timeout} Sekunden überschritten")
        if returncode != 0 or status == "ERROR":
            raise ValueError(
                f"Client-Sicherheitsstatus-Übertragung fehlgeschlagen (rc {returncode}): {_safe_error_text(error)}"
            )
        normalized_status = "saved" if status == "PRESENT" else status.lower()
        return normalized_status, borg_repository_id or None, transferred

def collect_client_borg_caches(archive: zipfile.ZipFile, progress: Callable[[dict], None] | None = None) -> list[dict]:
    """Stream assigned BBM client caches and their Borg security state into a cache backup.

    Disabled devices are recorded but deliberately not contacted. A connection
    or transfer failure on one enabled device is recorded as a warning and does
    not abort the remaining cache backup. Missing cache/security data is a valid
    state and is recorded explicitly.
    """
    entries: list[dict] = []
    targets = _target_rows()
    total = len(targets)
    for index, (host, repository) in enumerate(targets, start=1):
        metadata = _base_metadata(host, repository)
        if progress is not None:
            progress({
                "event": "target_start", "component": "cache", "index": index, "total": total,
                "host_id": int(host.id), "host_name": str(host.name),
                "repository_id": int(repository.id), "repository_name": str(repository.name),
                "bytes_done": 0,
            })
        if not host.enabled:
            metadata.update({
                "status": "skipped_disabled",
                "security_status": "skipped_disabled",
                "reason": "Gerät ist deaktiviert und wurde für das Cache-Backup nicht kontaktiert.",
            })
            entries.append(metadata)
            if progress is not None:
                progress({**metadata, "event": "target_done", "component": "complete", "index": index, "total": total, "bytes_done": 0})
            continue

        cache_arcname = f"{CLIENT_CACHE_ARCHIVE_ROOT}/host-{int(host.id)}/repository-{int(repository.id)}.tar"
        security_arcname = f"{CLIENT_SECURITY_ARCHIVE_ROOT}/host-{int(host.id)}/repository-{int(repository.id)}.tar"
        try:
            def on_cache_bytes(transferred: int) -> None:
                if progress is not None:
                    progress({
                        "event": "target_progress", "component": "cache", "index": index, "total": total,
                        "host_id": int(host.id), "host_name": str(host.name),
                        "repository_id": int(repository.id), "repository_name": str(repository.name),
                        "bytes_done": int(transferred),
                    })

            status, tar_bytes = (
                _stream_one_cache(archive, host, repository, cache_arcname, on_cache_bytes)
                if progress is not None else _stream_one_cache(archive, host, repository, cache_arcname)
            )

            if progress is not None:
                progress({
                    "event": "target_progress", "component": "security", "index": index, "total": total,
                    "host_id": int(host.id), "host_name": str(host.name),
                    "repository_id": int(repository.id), "repository_name": str(repository.name),
                    "bytes_done": int(tar_bytes),
                })

            def on_security_bytes(transferred: int) -> None:
                if progress is not None:
                    progress({
                        "event": "target_progress", "component": "security", "index": index, "total": total,
                        "host_id": int(host.id), "host_name": str(host.name),
                        "repository_id": int(repository.id), "repository_name": str(repository.name),
                        "bytes_done": int(tar_bytes) + int(transferred),
                    })

            security_status, borg_repository_id, security_tar_bytes = (
                _stream_one_security(archive, host, repository, security_arcname, on_security_bytes)
                if progress is not None else _stream_one_security(archive, host, repository, security_arcname)
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            reason = (
                f"Client-Borg-Zustand von Gerät „{host.name}“ / Repository „{repository.name}“ "
                f"konnte nicht gesichert werden: {exc}"
            )
            metadata.update({
                "status": "warning",
                "security_status": "warning",
                "reason": reason,
                "security_reason": reason,
                "warning": True,
            })
            entries.append(metadata)
            if progress is not None:
                progress({
                    **metadata,
                    "event": "target_done", "component": "complete", "index": index, "total": total,
                    "bytes_done": 0,
                })
            continue

        if status == "missing":
            metadata.update({
                "status": "missing",
                "reason": "Auf dem Gerät ist für dieses Repository noch kein BBM-Borg-Cache vorhanden.",
            })
        else:
            metadata.update({
                "status": "saved",
                "archive_path": cache_arcname,
                "tar_bytes": int(tar_bytes),
            })

        metadata["security_status"] = security_status
        metadata["borg_repository_id"] = borg_repository_id
        if borg_repository_id:
            metadata["security_path"] = f"$HOME/.config/borg/security/{borg_repository_id}"
        if security_status == "saved":
            metadata["security_archive_path"] = security_arcname
            metadata["security_tar_bytes"] = int(security_tar_bytes)
        elif security_status == "missing":
            metadata["security_reason"] = "Für dieses Repository ist auf dem Client noch kein Borg-Sicherheitsstatus vorhanden."
        elif security_status == "unresolved":
            metadata["security_reason"] = (
                "Der Borg-Sicherheitsstatus konnte keinem Repository eindeutig zugeordnet werden und wurde nicht gesichert."
            )

        entries.append(metadata)
        if progress is not None:
            progress({
                **metadata,
                "event": "target_done", "component": "complete", "index": index, "total": total,
                "bytes_done": int(metadata.get("tar_bytes") or 0) + int(metadata.get("security_tar_bytes") or 0),
            })
    return entries


def client_cache_summary(entries: list[dict]) -> dict[str, int]:
    return {
        "target_count": len(entries),
        "saved_count": sum(1 for item in entries if item.get("status") == "saved"),
        "missing_count": sum(1 for item in entries if item.get("status") == "missing"),
        "skipped_count": sum(1 for item in entries if str(item.get("status", "")).startswith("skipped_")),
        "warning_count": sum(1 for item in entries if item.get("status") == "warning"),
        "tar_bytes": sum(int(item.get("tar_bytes") or 0) for item in entries if item.get("status") == "saved"),
        "security_saved_count": sum(1 for item in entries if item.get("security_status") == "saved"),
        "security_missing_count": sum(1 for item in entries if item.get("security_status") == "missing"),
        "security_unresolved_count": sum(1 for item in entries if item.get("security_status") == "unresolved"),
        "security_tar_bytes": sum(
            int(item.get("security_tar_bytes") or 0) for item in entries if item.get("security_status") == "saved"
        ),
    }

_CLIENT_CACHE_RE = __import__("re").compile(r"^repository-([1-9][0-9]*)$")
_CLIENT_CACHE_ROLLBACK_RE = __import__("re").compile(
    r"^repository-([1-9][0-9]*)\.pre-bbm-restore-([0-9]{8}-[0-9]{6})$"
)


def _run_text_command(command: Command) -> str:
    timeout = command.timeout_seconds or COMMAND_TIMEOUT
    with _materialized_command(command) as argv:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **command.env} if command.env else None,
            start_new_session=True,
        )
        timer, timed_out = _start_timeout(process, timeout)
        try:
            stdout, stderr = process.communicate()
        finally:
            timer.cancel()
        if timed_out.is_set():
            raise ValueError(f"Client-Cache-Prüfung hat das Zeitlimit von {timeout} Sekunden überschritten")
        if process.returncode != 0:
            detail = _safe_error_text(stderr.decode("utf-8", errors="replace"))
            raise ValueError(f"Client-Cache-Prüfung fehlgeschlagen (rc {process.returncode}): {detail}")
        return stdout.decode("utf-8", errors="replace")


def _host_cache_assignments(host_ids: list[int] | set[int] | None = None) -> list[tuple[Host, set[int]]]:
    """Return selected devices and currently assigned repository IDs, including hosts without jobs."""
    selected_ids = {int(value) for value in (host_ids or []) if int(value) > 0}
    with SessionLocal() as db:
        host_query = select(Host).order_by(Host.name, Host.id)
        if selected_ids:
            host_query = host_query.where(Host.id.in_(selected_ids))
        hosts = list(db.scalars(host_query))
        row_query = select(Job.host_id, Job.repository_id)
        if selected_ids:
            row_query = row_query.where(Job.host_id.in_(selected_ids))
        rows = db.execute(row_query).all()
        assigned: dict[int, set[int]] = {}
        for host_id, repository_id in rows:
            if host_id is None or repository_id is None:
                continue
            assigned.setdefault(int(host_id), set()).add(int(repository_id))
        return [(host, assigned.get(int(host.id), set())) for host in hosts]


def _normalize_location(value: str | None) -> str:
    text = (value or "").strip().rstrip("/")
    if text.startswith("file://"):
        text = text[7:].rstrip("/")
    return text


def _repository_locations() -> dict[int, str]:
    with SessionLocal() as db:
        rows = db.execute(select(Repository.id, Repository.location)).all()
        return {
            int(repository_id): normalized
            for repository_id, location in rows
            if repository_id is not None and (normalized := _normalize_location(str(location or "")))
        }


def _decode_text(value: str) -> str | None:
    if not value or value == "-":
        return None
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
        text = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None
    if any(character in text for character in "\x00\r\n"):
        return None
    return text.strip() or None


def _decode_location(value: str) -> str | None:
    text = _decode_text(value)
    return _normalize_location(text) or None


def _parse_manifest_timestamp(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _valid_borg_id(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _parse_scan_paths(output: str) -> dict:
    """Return the actual cache/security roots reported by scan protocol V5."""
    result = {"home": None, "passwd_home": None, "bbm_cache": None, "legacy_caches": [], "security": None}
    for line in output.splitlines():
        parts = line.rstrip("\r").split("\t")
        if len(parts) == 2 and parts[0] == "SCAN_HOME":
            result["home"] = _decode_text(parts[1])
        elif len(parts) == 2 and parts[0] == "PASSWD_HOME":
            result["passwd_home"] = _decode_text(parts[1])
        elif len(parts) == 3 and parts[0] == "BBM_BASE":
            result["bbm_cache"] = {"path": _decode_text(parts[2]), "status": parts[1].lower()}
        elif len(parts) == 3 and parts[0] == "USER_CACHE_BASE5":
            path = _decode_text(parts[2])
            if path and all(item.get("path") != path for item in result["legacy_caches"]):
                result["legacy_caches"].append({"path": path, "status": parts[1].lower()})
        elif len(parts) == 3 and parts[0] == "SECURITY_BASE5":
            result["security"] = {"path": _decode_text(parts[2]), "status": parts[1].lower()}
    return result


def _parse_scan_output(
    output: str,
    assigned_repository_ids: set[int],
    assigned_locations: set[str] | None = None,
    known_locations: set[str] | None = None,
) -> list[dict]:
    lines = [line.rstrip("\r") for line in output.splitlines() if line.strip()]
    if not lines or lines[0] not in {"BBM_CLIENT_CACHE_SCAN_V1", "BBM_CLIENT_CACHE_SCAN_V2", "BBM_CLIENT_CACHE_SCAN_V3", "BBM_CLIENT_CACHE_SCAN_V4", "BBM_CLIENT_CACHE_SCAN_V5"}:
        raise ValueError("Ungültige Antwort bei der Client-Cache-Prüfung")
    assigned_locations = {_normalize_location(value) for value in (assigned_locations or set()) if _normalize_location(value)}
    known_locations = {_normalize_location(value) for value in (known_locations or set()) if _normalize_location(value)}

    cache_repo_ids: dict[str, str] = {}
    raw_security: list[dict] = []
    raw_user_cache: list[dict] = []
    entries: list[dict] = []

    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) == 4 and parts[0] == "ENTRY5":
            name, raw_size, raw_path = parts[1], parts[2], parts[3]
            path = _decode_text(raw_path)
            if raw_size in {"SYMLINK", "OTHER"}:
                entries.append({
                    "name": name,
                    "path": path,
                    "entry_type": "cache",
                    "kind": "unknown",
                    "repository_id": None,
                    "size_bytes": 0,
                    "selectable": False,
                    "default_selected": False,
                    "reason": "Kein reguläres BBM-Client-Cache-Verzeichnis; wird aus Sicherheitsgründen nicht bereinigt.",
                })
                continue
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            match = _CLIENT_CACHE_RE.fullmatch(name)
            if match:
                repository_id = int(match.group(1))
                active = repository_id in assigned_repository_ids
                entries.append({
                    "name": name,
                    "path": path,
                    "entry_type": "cache",
                    "kind": "active" if active else "orphan",
                    "repository_id": repository_id,
                    "borg_repository_id": None,
                    "size_bytes": size_bytes,
                    # An active BBM client cache is never part of normal cleanup,
                    # but may be selected explicitly for the separate reset action.
                    "selectable": True,
                    "default_selected": not active,
                    "reason": (
                        "Aktuelle Geräte-/Repository-Zuordnung vorhanden. Der BBM-Client-Cache wird verwendet und kann nur über die separate Zurücksetzen-Funktion mit Warnung gelöscht werden."
                        if active else
                        "Keine aktuelle Backup-Job-Zuordnung dieses Geräts zu diesem Repository vorhanden."
                    ),
                })
                continue
            rollback = _CLIENT_CACHE_ROLLBACK_RE.fullmatch(name)
            if rollback:
                repository_id = int(rollback.group(1))
                stamp = rollback.group(2)
                created_at = None
                try:
                    parsed = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
                    created_at = parsed.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
                entries.append({
                    "name": name,
                    "path": path,
                    "entry_type": "cache",
                    "kind": "rollback",
                    "repository_id": repository_id,
                    "size_bytes": size_bytes,
                    "created_at": created_at,
                    "selectable": True,
                    "default_selected": True,
                    "reason": "Vom BBM vor einer Client-Cache-Wiederherstellung angelegte Rückfall-Sicherung.",
                })
                continue
            entries.append({
                "name": name,
                "path": path,
                "entry_type": "cache",
                "kind": "unknown",
                "repository_id": None,
                "size_bytes": size_bytes,
                "selectable": False,
                "default_selected": False,
                "reason": "Unbekannter Eintrag im BBM-Client-Cache-Verzeichnis; wird nicht automatisch bereinigt.",
            })
            continue
        if len(parts) == 5 and parts[0] == "USER_CACHE_META5":
            continue
        if len(parts) == 5 and parts[0] == "USER_CACHE5":
            name, raw_size, raw_type, raw_path = parts[1], parts[2], parts[3], parts[4]
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            raw_user_cache.append({"name": name, "path": _decode_text(raw_path), "size_bytes": size_bytes, "raw_type": raw_type})
            continue
        if len(parts) == 7 and parts[0] == "SECURITY5":
            name, raw_size, raw_type, raw_location, raw_manifest, raw_path = parts[1:7]
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            raw_security.append({
                "name": name.lower(),
                "path": _decode_text(raw_path),
                "size_bytes": size_bytes,
                "raw_type": raw_type,
                "location": _decode_location(raw_location),
                "manifest_timestamp": _decode_text(raw_manifest),
            })
            continue
        if len(parts) == 3 and parts[0] == "CACHE_REPO":
            name, borg_repository_id = parts[1], parts[2].lower()
            if _CLIENT_CACHE_RE.fullmatch(name) and _valid_borg_id(borg_repository_id):
                cache_repo_ids[name] = borg_repository_id
            continue
        if len(parts) == 4 and parts[0] == "USER_CACHE_META":
            # CACHEDIR.TAG is standard cache-directory metadata, not a Borg
            # repository cache. Keep it out of the cleanup inventory.
            continue
        if len(parts) == 4 and parts[0] == "USER_CACHE":
            name, raw_size, raw_type = parts[1], parts[2], parts[3]
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            raw_user_cache.append({"name": name, "size_bytes": size_bytes, "raw_type": raw_type})
            continue
        if parts and parts[0] == "SECURITY" and len(parts) in {5, 6}:
            name, raw_size, raw_type, raw_location = parts[1], parts[2], parts[3], parts[4]
            raw_manifest = parts[5] if len(parts) == 6 else "-"
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            raw_security.append({
                "name": name.lower(),
                "size_bytes": size_bytes,
                "raw_type": raw_type,
                "location": _decode_location(raw_location),
                "manifest_timestamp": _decode_text(raw_manifest),
            })
            continue
        if len(parts) == 3 and parts[0] == "ENTRY":
            name, raw_size = parts[1], parts[2]
            if raw_size in {"SYMLINK", "OTHER"}:
                entries.append({
                    "name": name,
                    "entry_type": "cache",
                    "kind": "unknown",
                    "repository_id": None,
                    "size_bytes": 0,
                    "selectable": False,
                    "default_selected": False,
                    "reason": "Kein reguläres BBM-Cache-Verzeichnis; wird aus Sicherheitsgründen nicht bereinigt.",
                })
                continue
            try:
                size_bytes = max(0, int(raw_size)) * 1024
            except ValueError:
                size_bytes = 0
            match = _CLIENT_CACHE_RE.fullmatch(name)
            if match:
                repository_id = int(match.group(1))
                active = repository_id in assigned_repository_ids
                entries.append({
                    "name": name,
                    "entry_type": "cache",
                    "kind": "active" if active else "orphan",
                    "repository_id": repository_id,
                    "borg_repository_id": cache_repo_ids.get(name),
                    "size_bytes": size_bytes,
                    "selectable": True,
                    "default_selected": not active,
                    "reason": (
                        "Aktuelle Geräte-/Repository-Zuordnung vorhanden. Der BBM-Client-Cache wird verwendet und kann nur über die separate Zurücksetzen-Funktion mit Warnung gelöscht werden."
                        if active else
                        "Keine aktuelle Backup-Job-Zuordnung dieses Geräts zu diesem Repository vorhanden."
                    ),
                })
                continue
            rollback = _CLIENT_CACHE_ROLLBACK_RE.fullmatch(name)
            if rollback:
                repository_id = int(rollback.group(1))
                stamp = rollback.group(2)
                created_at = None
                try:
                    parsed = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
                    created_at = parsed.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
                entries.append({
                    "name": name,
                    "entry_type": "cache",
                    "kind": "rollback",
                    "repository_id": repository_id,
                    "size_bytes": size_bytes,
                    "created_at": created_at,
                    "selectable": True,
                    "default_selected": True,
                    "reason": "Vom BBM vor einer Client-Cache-Wiederherstellung angelegte Rückfall-Sicherung.",
                })
                continue
            entries.append({
                "name": name,
                "entry_type": "cache",
                "kind": "unknown",
                "repository_id": None,
                "size_bytes": size_bytes,
                "selectable": False,
                "default_selected": False,
                "reason": "Unbekannter Eintrag im BBM-Cache-Verzeichnis; wird nicht automatisch bereinigt.",
            })

    for entry in entries:
        if entry.get("entry_type") == "cache" and entry.get("name") in cache_repo_ids:
            entry["borg_repository_id"] = cache_repo_ids[str(entry.get("name"))]

    active_borg_ids: set[str] = set()
    orphan_borg_ids: set[str] = set()
    for cache_name, borg_repository_id in cache_repo_ids.items():
        match = _CLIENT_CACHE_RE.fullmatch(cache_name)
        if not match:
            continue
        if int(match.group(1)) in assigned_repository_ids:
            active_borg_ids.add(borg_repository_id)
        else:
            orphan_borg_ids.add(borg_repository_id)
    orphan_borg_ids -= active_borg_ids

    security_entries: list[dict] = []
    for raw in raw_security:
        name = str(raw["name"])
        location = raw.get("location")
        valid_id = _valid_borg_id(name)
        regular = raw.get("raw_type") == "DIR" and valid_id
        manifest_timestamp = raw.get("manifest_timestamp")
        manifest_dt = _parse_manifest_timestamp(manifest_timestamp)
        if not regular:
            security_entries.append({
                "name": name,
                "path": raw.get("path"),
                "entry_type": "security",
                "kind": "security_unknown",
                "repository_id": None,
                "borg_repository_id": name if valid_id else None,
                "location": location,
                "manifest_timestamp": manifest_timestamp,
                "manifest_timestamp_utc": manifest_dt.isoformat() if manifest_dt else None,
                "size_bytes": int(raw.get("size_bytes") or 0),
                "selectable": False,
                "default_selected": False,
                "reason": "Unbekannter oder nicht regulärer Borg-Sicherheitsstatus; kein sicher löschbares Verzeichnis.",
            })
            continue
        if name in active_borg_ids or (location is not None and location in assigned_locations):
            kind = "security_active"
            reason = "Borg-Sicherheitsstatus ist einem aktuell zugeordneten Repository dieses Geräts zugeordnet."
        elif name in orphan_borg_ids or (location is not None and location in known_locations and location not in assigned_locations):
            kind = "security_orphan"
            reason = "Borg-Sicherheitsstatus gehört zu einem BBM-Repository, das diesem Gerät nicht mehr zugeordnet ist."
        else:
            kind = "security_unknown"
            reason = "Borg-Sicherheitsstatus kann keinem BBM-Repository eindeutig zugeordnet werden; manuelle Auswahl zur Löschung ist möglich."
        security_entries.append({
            "name": name,
            "path": raw.get("path"),
            "entry_type": "security",
            "kind": kind,
            "repository_id": None,
            "borg_repository_id": name,
            "location": location,
            "manifest_timestamp": manifest_timestamp,
            "manifest_timestamp_utc": manifest_dt.isoformat() if manifest_dt else None,
            "size_bytes": int(raw.get("size_bytes") or 0),
            "selectable": kind != "security_active",
            "default_selected": kind == "security_orphan",
            "reason": reason,
        })

    # A security directory is keyed by repository ID, so two directories with the
    # same name cannot coexist. Duplicate candidates are therefore detected as
    # different repository IDs that record the same repository location.  Borg's
    # manifest-timestamp is used only when both values are parseable; active state
    # is never made deletable merely because another timestamp is newer.
    by_location: dict[str, list[dict]] = {}
    for item in security_entries:
        if item.get("location") and item.get("borg_repository_id") and item.get("manifest_timestamp_utc"):
            by_location.setdefault(str(item["location"]), []).append(item)
    for location, group in by_location.items():
        if len(group) < 2:
            continue
        dated = [(item, _parse_manifest_timestamp(item.get("manifest_timestamp"))) for item in group]
        dated = [(item, stamp) for item, stamp in dated if stamp is not None]
        if len(dated) < 2:
            for item in group:
                item["duplicate_state"] = "ambiguous"
                item["reason"] += " Mehrere Security-Verzeichnisse verwenden denselben Standort, aber die manifest-timestamp-Werte sind nicht eindeutig vergleichbar."
            continue
        newest_stamp = max(stamp for _item, stamp in dated)
        newest = [item for item, stamp in dated if stamp == newest_stamp]
        if len(newest) != 1:
            for item in group:
                item["duplicate_state"] = "ambiguous"
                item["reason"] += " Mehrere Security-Verzeichnisse verwenden denselben Standort und denselben neuesten manifest-timestamp; keine automatische Duplikatbewertung."
            continue
        newest_item = newest[0]
        newest_item["duplicate_state"] = "newest"
        newest_item["duplicate_newest_id"] = newest_item.get("name")
        for item, stamp in dated:
            if item is newest_item:
                continue
            item["duplicate_state"] = "older"
            item["duplicate_newest_id"] = newest_item.get("name")
            if item.get("kind") == "security_active" and item.get("name") in active_borg_ids:
                item["reason"] += " Ein weiterer Security-Stand für denselben Standort hat einen neueren manifest-timestamp; die Borg-ID ist jedoch über den aktiven BBM-Cache bestätigt und bleibt deshalb geschützt."
                item["selectable"] = False
                item["default_selected"] = False
            else:
                item["kind"] = "security_duplicate_old"
                item["selectable"] = True
                item["default_selected"] = True
                item["reason"] = (
                    f"Älterer Borg-Sicherheitsstatus für denselben Repository-Standort; neuerer Stand: {newest_item.get('name')} "
                    f"({newest_item.get('manifest_timestamp') or 'ohne Zeitstempel'})."
                )

    security_by_id = {
        str(item.get("borg_repository_id")): item
        for item in security_entries
        if item.get("borg_repository_id")
    }
    user_cache_entries: list[dict] = []
    for raw in raw_user_cache:
        original_name = str(raw.get("name") or "")
        normalized_name = original_name.lower()
        valid_id = _valid_borg_id(normalized_name)
        raw_type = str(raw.get("raw_type") or "")
        regular_repo_cache = raw_type == "DIR" and valid_id
        security = security_by_id.get(normalized_name) if valid_id else None
        location = security.get("location") if security else None
        if regular_repo_cache and (normalized_name in active_borg_ids or (security and security.get("kind") == "security_active")):
            kind = "user_cache_active"
            selectable = True
            default_selected = False
            reason = (
                "Legacy-Borg-Cache ist derselben aktuell zugeordneten Borg-Repository-ID zuordenbar, wird vom BBM jedoch nicht verwendet. "
                "Der BBM nutzt stattdessen seinen eigenen BBM-Client-Cache; dieser Legacy-Cache kann bei Bedarf manuell gelöscht werden."
            )
        elif regular_repo_cache and (normalized_name in orphan_borg_ids or (security and security.get("kind") in {"security_orphan", "security_duplicate_old"})):
            kind = "user_cache_orphan"
            selectable = True
            default_selected = True
            reason = "Legacy-Borg-Cache gehört zu einem bekannten, nicht mehr aktiven beziehungsweise älteren Repository-Zustand dieses Geräts."
        elif regular_repo_cache:
            kind = "user_cache_unknown"
            selectable = True
            default_selected = False
            reason = "Legacy-Borg-Cache außerhalb des BBM kann keinem aktuellen BBM-Repository zugeordnet werden; manuelle Auswahl zur Löschung ist möglich."
        elif raw_type in {"DIR", "FILE"}:
            kind = "user_cache_misc"
            selectable = True
            default_selected = False
            reason = "Nicht standardmäßiger beziehungsweise älterer Eintrag im Legacy-Borg-Cache-Verzeichnis; manuelle Auswahl zur Löschung ist möglich."
        else:
            kind = "user_cache_misc"
            selectable = False
            default_selected = False
            reason = "Nicht regulärer Eintrag im Legacy-Borg-Cache-Verzeichnis; wird aus Sicherheitsgründen nicht zur Bereinigung freigegeben."
        user_cache_entries.append({
            "name": normalized_name if valid_id else original_name,
            "path": raw.get("path"),
            "entry_type": "user_cache",
            "kind": kind,
            "repository_id": None,
            "borg_repository_id": normalized_name if valid_id else None,
            "location": location,
            "raw_type": raw_type,
            "size_bytes": int(raw.get("size_bytes") or 0),
            "selectable": selectable,
            "default_selected": default_selected,
            "reason": reason,
        })

    entries.extend(user_cache_entries)
    entries.extend(security_entries)
    return entries


def scan_client_borg_caches(host_ids: list[int] | set[int] | None = None) -> dict:
    """Inspect selected clients without changing BBM cache, normal Borg cache, or security state."""
    from app.runner import client_borg_cache_scan_command

    requested_ids = {int(value) for value in (host_ids or []) if int(value) > 0}
    repository_locations = _repository_locations()
    known_locations = set(repository_locations.values())
    devices: list[dict] = []
    assignments = _host_cache_assignments(requested_ids or None)
    found_ids = {int(host.id) for host, _assigned in assignments}
    for host, assigned_repository_ids in assignments:
        assigned_locations = {
            repository_locations[repository_id]
            for repository_id in assigned_repository_ids
            if repository_id in repository_locations
        }
        base = {
            "host_id": int(host.id),
            "host_name": str(host.name),
            "enabled": bool(host.enabled),
            "assigned_repository_ids": sorted(assigned_repository_ids),
        }
        if not host.enabled:
            devices.append({**base, "status": "skipped_disabled", "entries": [], "error": None})
            continue
        try:
            output = _run_text_command(client_borg_cache_scan_command(host))
            entries = _parse_scan_output(output, assigned_repository_ids, assigned_locations, known_locations)
            devices.append({**base, "status": "ok", "entries": entries, "scan_paths": _parse_scan_paths(output), "error": None})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            devices.append({**base, "status": "error", "entries": [], "error": str(exc)})

    all_entries = [entry for device in devices for entry in device.get("entries", [])]
    def chosen(kind: str) -> list[dict]:
        return [entry for entry in all_entries if entry.get("kind") == kind]

    orphan = chosen("orphan")
    rollback = chosen("rollback")
    security_orphan = chosen("security_orphan")
    security_unknown = chosen("security_unknown")
    security_duplicate_old = chosen("security_duplicate_old")
    user_cache_orphan = chosen("user_cache_orphan")
    user_cache_unknown = chosen("user_cache_unknown")
    user_cache_misc = chosen("user_cache_misc")
    return {
        "devices": devices,
        "selection_mode": "selected" if requested_ids else "all",
        "requested_host_ids": sorted(requested_ids),
        "missing_host_ids": sorted(requested_ids - found_ids),
        "device_count": len(devices),
        "checked_device_count": sum(1 for device in devices if device.get("status") == "ok"),
        "error_device_count": sum(1 for device in devices if device.get("status") == "error"),
        "skipped_device_count": sum(1 for device in devices if device.get("status") == "skipped_disabled"),
        "orphan_count": len(orphan),
        "orphan_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in orphan),
        "rollback_count": len(rollback),
        "rollback_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in rollback),
        "security_orphan_count": len(security_orphan),
        "security_orphan_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in security_orphan),
        "security_unknown_count": len(security_unknown),
        "security_unknown_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in security_unknown),
        "security_duplicate_old_count": len(security_duplicate_old),
        "security_duplicate_old_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in security_duplicate_old),
        "user_cache_orphan_count": len(user_cache_orphan),
        "user_cache_orphan_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in user_cache_orphan),
        "user_cache_unknown_count": len(user_cache_unknown),
        "user_cache_unknown_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in user_cache_unknown),
        "user_cache_misc_count": len(user_cache_misc),
        "user_cache_misc_size_bytes": sum(int(entry.get("size_bytes") or 0) for entry in user_cache_misc),
    }


def cleanup_client_borg_caches(kind: str, requested: list[dict]) -> dict:
    """Delete selected BBM caches, legacy Borg caches, security state, or restore safety copies."""
    from app.runner import (
        client_borg_cache_cleanup_command,
        client_borg_cache_scan_command,
        client_borg_security_cleanup_command,
        client_borg_user_cache_cleanup_command,
    )

    if kind not in {"orphan", "rollback", "security", "security_orphan", "user_cache", "reset"}:
        raise ValueError("Ungültige Client-Cache-Bereinigungsart")
    if not requested:
        raise ValueError("Keine Client-Cache-Einträge zur Bereinigung ausgewählt")

    requested_by_host: dict[int, list[dict]] = {}
    for item in requested:
        host_id = int(item.get("host_id") or 0)
        raw_name = str(item.get("name") or "")
        name = raw_name if kind == "user_cache" else raw_name.lower()
        raw_path = str(item.get("path") or "").strip()
        if kind in {"orphan", "reset"}:
            valid = bool(_CLIENT_CACHE_RE.fullmatch(name))
        elif kind == "rollback":
            valid = bool(_CLIENT_CACHE_ROLLBACK_RE.fullmatch(name))
        elif kind == "user_cache":
            valid = bool(
                name
                and name not in {".", ".."}
                and "/" not in name
                and "\x00" not in name
                and "\r" not in name
                and "\n" not in name
                and len(name.encode("utf-8")) <= 255
                and name.lower() != "cachedir.tag"
                and (not raw_path or (raw_path.startswith("/") and "\x00" not in raw_path and "\r" not in raw_path and "\n" not in raw_path))
            )
        else:
            valid = _valid_borg_id(name)
        if host_id <= 0 or not valid:
            raise ValueError("Ungültige Client-Cache-Auswahl")
        requested_by_host.setdefault(host_id, []).append({"name": name, "path": raw_path or None})

    if kind == "reset":
        # Resetting a cache that Borg or a cache-backup task may currently modify
        # risks an inconsistent local state. Block the operation before any SSH
        # deletion is attempted.
        with SessionLocal() as db:
            active_run = db.scalar(select(Run.id).where(Run.status.in_(["queued", "running"])).limit(1))
        if active_run is not None:
            raise ValueError("BBM-Client-Caches können nur ohne laufende oder wartende Ausführungen zurückgesetzt werden")
        from app.manager_backup_progress import current_task as current_manager_backup_task
        backup_task = current_manager_backup_task(include_last=False)
        if backup_task and backup_task.get("status") in {"queued", "running"}:
            raise ValueError("BBM-Client-Caches können während eines laufenden Manager-/Cache-Backups nicht zurückgesetzt werden")

    assignments = {int(host.id): (host, assigned) for host, assigned in _host_cache_assignments(set(requested_by_host))}
    repository_locations = _repository_locations() if kind in {"security", "security_orphan", "user_cache", "reset"} else {}
    known_locations = set(repository_locations.values())
    removed_count = 0
    removed_names: list[dict] = []
    skipped: list[dict] = []
    for host_id, targets in requested_by_host.items():
        current = assignments.get(host_id)
        if current is None:
            skipped.extend({"host_id": host_id, "name": target["name"], "reason": "Gerät existiert nicht mehr."} for target in targets)
            continue
        host, assigned_repository_ids = current
        if not host.enabled:
            skipped.extend({"host_id": host_id, "name": target["name"], "reason": "Gerät ist deaktiviert."} for target in targets)
            continue
        safe_values: list[str] = []
        if kind == "reset":
            # Re-scan immediately before deletion. Only a currently active,
            # correctly assigned BBM cache may pass the reset path.
            assigned_locations = {
                repository_locations[repository_id]
                for repository_id in assigned_repository_ids
                if repository_id in repository_locations
            }
            try:
                current_entries = _parse_scan_output(
                    _run_text_command(client_borg_cache_scan_command(host)),
                    assigned_repository_ids,
                    assigned_locations,
                    known_locations,
                )
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                skipped.extend({
                    "host_id": host_id, "host_name": str(host.name), "name": target["name"],
                    "reason": f"Client-Zustand konnte vor dem Zurücksetzen nicht erneut geprüft werden: {exc}",
                } for target in targets)
                continue
            for target in targets:
                name = target["name"]
                candidates = [
                    entry for entry in current_entries
                    if entry.get("entry_type") == "cache"
                    and entry.get("kind") == "active"
                    and str(entry.get("name") or "") == name
                ]
                entry = candidates[0] if len(candidates) == 1 else None
                if not entry or int(entry.get("repository_id") or 0) not in assigned_repository_ids:
                    skipped.append({
                        "host_id": host_id, "name": name,
                        "reason": "BBM-Client-Cache ist nicht mehr eindeutig aktiv zugeordnet und wurde nicht zurückgesetzt.",
                    })
                else:
                    safe_values.append(name)
        elif kind in {"security", "security_orphan", "user_cache"}:
            assigned_locations = {
                repository_locations[repository_id]
                for repository_id in assigned_repository_ids
                if repository_id in repository_locations
            }
            try:
                current_entries = _parse_scan_output(
                    _run_text_command(client_borg_cache_scan_command(host)),
                    assigned_repository_ids,
                    assigned_locations,
                    known_locations,
                )
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                skipped.extend({
                    "host_id": host_id, "host_name": str(host.name), "name": target["name"],
                    "reason": f"Client-Zustand konnte vor dem Löschen nicht erneut geprüft werden: {exc}",
                } for target in targets)
                continue
            for target in targets:
                name = target["name"]
                requested_path = target.get("path")
                candidates = [
                    entry for entry in current_entries
                    if str(entry.get("entry_type") or "") == ("user_cache" if kind == "user_cache" else "security")
                    and str(entry.get("name") or "") == name
                    and (not requested_path or str(entry.get("path") or "") == requested_path)
                ]
                entry = candidates[0] if len(candidates) == 1 else None
                if kind == "user_cache":
                    allowed = entry and entry.get("kind") in {"user_cache_active", "user_cache_orphan", "user_cache_unknown", "user_cache_misc"} and entry.get("selectable")
                else:
                    allowed_kinds = {"security_orphan"} if kind == "security_orphan" else {"security_orphan", "security_unknown", "security_duplicate_old"}
                    allowed = entry and entry.get("kind") in allowed_kinds and entry.get("selectable")
                if not allowed:
                    skipped.append({
                        "host_id": host_id, "name": name,
                        "reason": "Eintrag ist nicht mehr eindeutig in einer zur Löschung freigegebenen Kategorie und wurde nicht gelöscht.",
                    })
                else:
                    safe_values.append(str(entry.get("path") or name) if kind == "user_cache" else name)
        else:
            for target in targets:
                name = target["name"]
                if kind == "orphan":
                    repository_id = int(_CLIENT_CACHE_RE.fullmatch(name).group(1))
                    if repository_id in assigned_repository_ids:
                        skipped.append({
                            "host_id": host_id, "name": name,
                            "reason": "Cache ist inzwischen wieder einem Backup-Job zugeordnet und wurde nicht gelöscht.",
                        })
                        continue
                safe_values.append(name)
        if not safe_values:
            continue
        try:
            if kind in {"security", "security_orphan"}:
                command = client_borg_security_cleanup_command(host, safe_values)
            elif kind == "user_cache":
                command = client_borg_user_cache_cleanup_command(host, safe_values)
            else:
                command = client_borg_cache_cleanup_command(host, safe_values)
            output = _run_text_command(command)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            skipped.extend({
                "host_id": host_id, "host_name": str(host.name), "name": value,
                "reason": f"Bereinigung auf dem Gerät fehlgeschlagen: {exc}",
            } for value in safe_values)
            continue
        for line in output.splitlines():
            parts = line.rstrip("\r").split("\t")
            if len(parts) >= 2 and parts[0] == "REMOVED":
                removed_count += 1
                removed_names.append({"host_id": host_id, "host_name": str(host.name), "name": parts[1]})
            elif len(parts) >= 2 and parts[0] in {"SKIPPED", "MISSING", "FAILED"}:
                skipped.append({
                    "host_id": host_id, "host_name": str(host.name), "name": parts[1],
                    "reason": parts[2] if len(parts) >= 3 else parts[0].lower(),
                })

    refresh_ids = sorted(requested_by_host)
    return {
        "removed_count": removed_count,
        "removed": removed_names,
        "skipped": skipped,
        "status": scan_client_borg_caches(refresh_ids),
    }


def restore_client_borg_cache_stream(host: Host, repository_id: int, source: BinaryIO) -> dict:
    """Stream one cache tar from an authenticated Manager backup to its device."""
    command = client_borg_cache_restore_command(host, repository_id)
    timeout = command.timeout_seconds or COMMAND_TIMEOUT
    with _materialized_command(command) as argv, tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env={**os.environ, **command.env} if command.env else None,
            start_new_session=True,
        )
        timer, timed_out = _start_timeout(process, timeout)
        write_error: Exception | None = None
        try:
            if process.stdin is None:
                raise ValueError("SSH-Prozess akzeptiert keinen Client-Cache-Datenstrom")
            try:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                process.stdin.close()
            except (BrokenPipeError, OSError) as exc:
                write_error = exc
                try:
                    process.stdin.close()
                except OSError:
                    pass
            returncode = process.wait()
        finally:
            timer.cancel()
        stdout_file.seek(0)
        output = stdout_file.read().decode("utf-8", errors="replace")
        stderr_file.seek(0)
        error = stderr_file.read().decode("utf-8", errors="replace")
        if timed_out.is_set():
            raise ValueError(f"Client-Cache-Wiederherstellung hat das Zeitlimit von {timeout} Sekunden überschritten")
        if returncode != 0 or write_error is not None:
            detail = _safe_error_text(error or str(write_error or ""))
            raise ValueError(f"Client-Cache-Wiederherstellung fehlgeschlagen (rc {returncode}): {detail}")
        if "BBM_CLIENT_CACHE_RESTORED" not in output:
            raise ValueError("Gerät hat die erfolgreiche Client-Cache-Wiederherstellung nicht bestätigt")
        previous = None
        for line in output.splitlines():
            if line.startswith("BBM_PREVIOUS_CACHE="):
                previous = line.split("=", 1)[1].strip() or None
        return {
            "status": "restored",
            "host_id": int(host.id),
            "repository_id": int(repository_id),
            "previous_cache": previous,
        }
def restore_client_borg_security_stream(host: Host, borg_repository_id: str, source: BinaryIO) -> dict:
    """Restore missing Borg security state while preserving any existing local state."""
    command = client_borg_security_restore_command(host, borg_repository_id)
    timeout = command.timeout_seconds or COMMAND_TIMEOUT
    with _materialized_command(command) as argv, tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env={**os.environ, **command.env} if command.env else None,
            start_new_session=True,
        )
        timer, timed_out = _start_timeout(process, timeout)
        write_error: Exception | None = None
        try:
            if process.stdin is None:
                raise ValueError("SSH-Prozess akzeptiert keinen Client-Sicherheitsstatus-Datenstrom")
            try:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                process.stdin.close()
            except (BrokenPipeError, OSError) as exc:
                write_error = exc
                try:
                    process.stdin.close()
                except OSError:
                    pass
            returncode = process.wait()
        finally:
            timer.cancel()
        stdout_file.seek(0)
        output = stdout_file.read().decode("utf-8", errors="replace")
        stderr_file.seek(0)
        error = stderr_file.read().decode("utf-8", errors="replace")
        if timed_out.is_set():
            raise ValueError(f"Client-Sicherheitsstatus-Wiederherstellung hat das Zeitlimit von {timeout} Sekunden überschritten")
        if returncode != 0 or write_error is not None:
            detail = _safe_error_text(error or str(write_error or ""))
            raise ValueError(f"Client-Sicherheitsstatus-Wiederherstellung fehlgeschlagen (rc {returncode}): {detail}")
        if "BBM_CLIENT_SECURITY_KEPT_EXISTING" in output:
            return {"status": "kept_existing", "borg_repository_id": str(borg_repository_id)}
        if "BBM_CLIENT_SECURITY_RESTORED" not in output:
            raise ValueError("Gerät hat die erfolgreiche Wiederherstellung des Client-Sicherheitsstatus nicht bestätigt")
        return {"status": "restored", "borg_repository_id": str(borg_repository_id)}

