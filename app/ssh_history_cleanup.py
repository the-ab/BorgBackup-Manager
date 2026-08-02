from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.config import DATA_DIR
from app.database import engine
from app.run_logs import delete_run_log, run_log_path
from app.sqlite_maintenance import mark_manager_vacuum_pending, retry_sqlite

MAINTENANCE_BACKUP_DIR = DATA_DIR / "maintenance-backups"
_SANITIZED_PREVIEW = "Gespeicherte SSH-Aktion (historischer Lauf; Befehlsinhalt entfernt)"
_SAFE_PREVIEW_PREFIXES = (
    "Gespeicherte SSH-Aktion:",
    "Gespeicherte SSH-Aktion auf Gerät ",
    _SANITIZED_PREVIEW,
)
_LEGACY_CONTROLLER_MARKER = "[temporärer Controller-Schlüssel]".encode("utf-8")
_LEGACY_SHELL_MARKER = b" -- sh -lc "
_LEGACY_MARKER_WINDOW = 4096



def _preview_is_unsafe(value: Any) -> bool:
    preview = str(value or "").strip()
    if not preview:
        return False
    return not preview.startswith(_SAFE_PREVIEW_PREFIXES)


def legacy_ssh_run_history_status(target_engine: Engine = engine) -> dict[str, int | bool]:
    if target_engine.dialect.name != "sqlite":
        return {"supported": False, "rows": 0}

    def inspect_rows() -> dict[str, int | bool]:
        with target_engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if "runs" not in tables:
                return {"supported": True, "rows": 0}
            rows = connection.execute(text(
                "SELECT id,command_preview FROM runs WHERE action='ssh-command'"
            )).mappings().all()
            unsafe_rows = [row for row in rows if _preview_is_unsafe(row["command_preview"])]
            historical_ids = [
                int(row["id"])
                for row in rows
                if _preview_is_unsafe(row["command_preview"])
                or str(row["command_preview"] or "").strip() == _SANITIZED_PREVIEW
            ]
            return {
                "supported": True,
                "rows": len(unsafe_rows),
                "run_logs": sum(1 for run_id in historical_ids if run_log_path(run_id).is_file()),
            }

    return retry_sqlite(inspect_rows)


def sanitize_legacy_ssh_run_history(
    target_engine: Engine = engine,
    *,
    mark_vacuum: bool = True,
) -> dict[str, int | bool]:
    """Remove command-bearing previews and related detail from legacy SSH runs.

    Releases before v1.3.3 persisted the complete ``sh -lc`` command in
    ``runs.command_preview``. Those rows remain active records, so dropping the
    old action table and running VACUUM cannot remove them. For every affected
    historical run we retain status, timestamps, target/action label and other
    non-secret metadata, but remove all free-form execution detail and the
    file-backed run log because either may repeat credentials from the command.
    """
    if target_engine.dialect.name != "sqlite":
        return {
            "supported": False,
            "rows_sanitized": 0,
            "notification_details_sanitized": 0,
            "run_logs_removed": 0,
            "vacuum_pending": False,
        }

    affected_ids: list[int] = []
    historical_ids: list[int] = []
    notification_rows = 0

    def sanitize_rows() -> None:
        nonlocal affected_ids, historical_ids, notification_rows
        with target_engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            if "runs" not in tables:
                return
            rows = connection.execute(text(
                "SELECT id,command_preview FROM runs WHERE action='ssh-command' ORDER BY id"
            )).mappings().all()
            affected_ids = [int(row["id"]) for row in rows if _preview_is_unsafe(row["command_preview"])]
            historical_ids = [
                int(row["id"])
                for row in rows
                if _preview_is_unsafe(row["command_preview"])
                or str(row["command_preview"] or "").strip() == _SANITIZED_PREVIEW
            ]
            # Redact both newly detected and already marked historical rows.
            # Repeating the update makes an interrupted earlier cleanup
            # self-healing without touching current safe SSH action runs.
            for run_id in historical_ids:
                connection.execute(text(
                    """
                    UPDATE runs
                       SET command_preview=:preview,
                           output='',
                           error='',
                           log_output='',
                           warning_summary_json=''
                     WHERE id=:run_id
                    """
                ), {"preview": _SANITIZED_PREVIEW, "run_id": run_id})
            if historical_ids and "notification_deliveries" in tables:
                for run_id in historical_ids:
                    cursor = connection.execute(text(
                        """
                        UPDATE notification_deliveries
                           SET detail='Historische SSH-Aktionsdetails aus Sicherheitsgründen entfernt.'
                         WHERE run_id=:run_id
                           AND COALESCE(detail,'')<>''
                           AND detail<>'Historische SSH-Aktionsdetails aus Sicherheitsgründen entfernt.'
                        """
                    ), {"run_id": run_id})
                    notification_rows += int(cursor.rowcount or 0)

    retry_sqlite(sanitize_rows, attempts=10, delay_seconds=0.35)

    removed_logs = 0
    for run_id in historical_ids:
        # The sanitized preview remains as a persistent non-secret marker, so a
        # failed deletion or process interruption is retried at every startup
        # and manual maintenance pass until the file is actually gone.
        path = run_log_path(run_id)
        existed = path.is_file()
        delete_run_log(run_id)
        if existed and not path.exists():
            removed_logs += 1

    raw_marker_files = manager_database_legacy_marker_files(target_engine)
    vacuum_required = bool(affected_ids or raw_marker_files)
    if vacuum_required and mark_vacuum:
        mark_manager_vacuum_pending()

    return {
        "supported": True,
        "rows_sanitized": len(affected_ids),
        "notification_details_sanitized": notification_rows,
        "run_logs_removed": removed_logs,
        "raw_marker_files": [path.name for path in raw_marker_files],
        "vacuum_pending": bool(vacuum_required and mark_vacuum),
    }



def _file_contains_legacy_preview(path: Path) -> bool:
    """Detect the exact legacy saved-action preview shape in raw SQLite pages.

    Ordinary BBM SSH previews also contain the controller-key placeholder and
    may use ``sh -c``. Only the old saved-action form combines that placeholder
    with ``-- sh -lc`` within the same short preview, which avoids false
    positives from normal backup and repository runs.
    """
    if not path.is_file():
        return False
    overlap = _LEGACY_MARKER_WINDOW + len(_LEGACY_CONTROLLER_MARKER) + len(_LEGACY_SHELL_MARKER)
    tail = b""
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    return False
                payload = tail + chunk
                position = 0
                while True:
                    position = payload.find(_LEGACY_CONTROLLER_MARKER, position)
                    if position < 0:
                        break
                    window_end = min(len(payload), position + _LEGACY_MARKER_WINDOW)
                    if _LEGACY_SHELL_MARKER in payload[position:window_end]:
                        return True
                    position += len(_LEGACY_CONTROLLER_MARKER)
                tail = payload[-overlap:]
    except OSError:
        return True


def manager_database_legacy_marker_files(target_engine: Engine = engine) -> list[Path]:
    if target_engine.dialect.name != "sqlite":
        return []
    database = target_engine.url.database
    if not database or database == ":memory:":
        return []
    path = Path(database)
    candidates = (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    )
    return [candidate for candidate in candidates if _file_contains_legacy_preview(candidate)]


def verify_no_legacy_ssh_plaintext_markers(target_engine: Engine = engine) -> None:
    matches = manager_database_legacy_marker_files(target_engine)
    if matches:
        names = ", ".join(path.name for path in matches)
        raise RuntimeError(f"Historische SSH-Klartextvorschau weiterhin in SQLite-Datei erkannt: {names}")

def _sqlite_family(path: Path) -> tuple[Path, Path, Path]:
    return (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    )


def _sqlite_backup_contains_sensitive_ssh_history(path: Path) -> bool:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
            tables = {str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "host_ssh_actions" in tables:
                columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(host_ssh_actions)")}
                if "command" in columns:
                    count = int(connection.execute("SELECT COUNT(*) FROM host_ssh_actions").fetchone()[0])
                    if count > 0:
                        return True
            if "runs" in tables:
                for (preview,) in connection.execute(
                    "SELECT command_preview FROM runs WHERE action='ssh-command'"
                ):
                    if _preview_is_unsafe(preview):
                        return True
    except (OSError, sqlite3.Error):
        # A broken or unreadable maintenance copy must not be trusted as a safe
        # rollback artifact. Treat it as sensitive so it is removed.
        return True

    return any(_file_contains_legacy_preview(candidate) for candidate in _sqlite_family(path))


def sensitive_maintenance_backup_paths(
    backup_dir: Path = MAINTENANCE_BACKUP_DIR,
) -> list[Path]:
    if not backup_dir.is_dir():
        return []
    result: list[Path] = []
    for path in sorted(backup_dir.glob("manager-before-cleanup-*.sqlite3")):
        if _sqlite_backup_contains_sensitive_ssh_history(path):
            result.append(path)
    return result


def purge_sensitive_maintenance_backups(
    backup_dir: Path = MAINTENANCE_BACKUP_DIR,
) -> int:
    removed = 0
    for path in sensitive_maintenance_backup_paths(backup_dir):
        existed = path.exists()
        for candidate in _sqlite_family(path):
            candidate.unlink(missing_ok=True)
        if existed and not path.exists():
            removed += 1
    return removed
