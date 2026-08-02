from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from app.archive_mounts import archive_mount_is_active
from app.config import DATA_DIR, DATABASE_URL, SECURITY_DATABASE_PATH
from app.database import engine
from app.security_store import delete_orphan_host_ssh_actions, host_ssh_action_host_ids
from app.host_ssh_actions import migrate_legacy_host_ssh_actions
from app.ssh_history_cleanup import (
    legacy_ssh_run_history_status,
    purge_sensitive_maintenance_backups,
    sanitize_legacy_ssh_run_history,
    sensitive_maintenance_backup_paths,
)
from app.sqlite_maintenance import mark_manager_vacuum_pending, manager_vacuum_pending

MAINTENANCE_BACKUP_DIR = DATA_DIR / "maintenance-backups"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _database_path() -> Path:
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix) or DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        raise ValueError("Datenbankbereinigung wird nur für eine dateibasierte SQLite-Datenbank unterstützt")
    return Path(DATABASE_URL[len(prefix):])


def _iso(value: datetime) -> str:
    return value.isoformat()


def _table_names(connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def _safe_json_ids(value: Any) -> list[int]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return sorted({int(item) for item in parsed if not isinstance(item, bool) and str(item).isdigit() and int(item) > 0})


def database_cleanup_preview() -> dict[str, Any]:
    now = _utcnow()
    stale_run_cutoff = _iso(now - timedelta(hours=24))
    stale_mount_cutoff = now - timedelta(minutes=10)
    orphan_delivery_cutoff = _iso(now - timedelta(days=30))
    result: dict[str, Any] = {
        "supported": engine.dialect.name == "sqlite",
        "database": str(_database_path()) if engine.dialect.name == "sqlite" else str(engine.url),
        "stale_active_runs": 0,
        "stale_mount_rows": 0,
        "orphan_repository_access_rows": 0,
        "orphan_host_action_rows": 0,
        "legacy_host_action_table": False,
        "legacy_host_action_rows": 0,
        "legacy_ssh_run_rows": 0,
        "legacy_ssh_run_logs": 0,
        "sensitive_maintenance_backups": 0,
        "vacuum_pending": manager_vacuum_pending(),
        "orphan_notification_deliveries": 0,
        "schedule_rows_with_invalid_targets": 0,
        "foreign_key_violations": 0,
        "freelist_pages": 0,
        "page_count": 0,
        "page_size": 0,
    }
    if engine.dialect.name != "sqlite":
        return result
    with engine.connect() as connection:
        tables = _table_names(connection)
        if "runs" in tables:
            result["stale_active_runs"] = int(connection.execute(text(
                "SELECT COUNT(*) FROM runs WHERE status IN ('queued','running') AND created_at < :cutoff"
            ), {"cutoff": stale_run_cutoff}).scalar() or 0)
        if "manager_archive_mounts" in tables:
            rows = connection.execute(text("SELECT id,mount_path,updated_at,created_at FROM manager_archive_mounts")).mappings().all()
            stale = 0
            for row in rows:
                timestamp = row.get("updated_at") or row.get("created_at")
                try:
                    parsed = datetime.fromisoformat(str(timestamp)) if timestamp else None
                    if parsed is not None and parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    age_ok = parsed < stale_mount_cutoff if parsed is not None else True
                except (TypeError, ValueError):
                    age_ok = True
                if age_ok and not archive_mount_is_active(str(row.get("mount_path") or "")):
                    stale += 1
            result["stale_mount_rows"] = stale
        if "host_repository_access" in tables:
            result["orphan_repository_access_rows"] = int(connection.execute(text(
                "SELECT COUNT(*) FROM host_repository_access a LEFT JOIN hosts h ON h.id=a.host_id LEFT JOIN repositories r ON r.id=a.repository_id WHERE h.id IS NULL OR r.id IS NULL"
            )).scalar() or 0)
        host_ids = set(connection.execute(text("SELECT id FROM hosts")).scalars()) if "hosts" in tables else set()
        result["orphan_host_action_rows"] = sum(
            1 for host_id in host_ssh_action_host_ids() if host_id not in host_ids
        )
        result["legacy_host_action_table"] = "host_ssh_actions" in tables
        if result["legacy_host_action_table"]:
            result["legacy_host_action_rows"] = int(
                connection.execute(text("SELECT COUNT(*) FROM host_ssh_actions")).scalar() or 0
            )
        if "notification_deliveries" in tables and "runs" in tables:
            result["orphan_notification_deliveries"] = int(connection.execute(text(
                "SELECT COUNT(*) FROM notification_deliveries d LEFT JOIN runs r ON r.id=d.run_id WHERE d.run_id IS NOT NULL AND r.id IS NULL AND d.created_at < :cutoff"
            ), {"cutoff": orphan_delivery_cutoff}).scalar() or 0)
        if "backup_schedules" in tables:
            host_ids = set(connection.execute(text("SELECT id FROM hosts")).scalars()) if "hosts" in tables else set()
            job_ids = set(connection.execute(text("SELECT id FROM jobs")).scalars()) if "jobs" in tables else set()
            repository_ids = set(connection.execute(text("SELECT id FROM repositories")).scalars()) if "repositories" in tables else set()
            invalid = 0
            for row in connection.execute(text("SELECT target_mode,target_host_ids_json,target_job_ids_json,target_repository_id FROM backup_schedules")).mappings():
                mode = str(row["target_mode"] or "")
                if mode == "hosts" and any(value not in host_ids for value in _safe_json_ids(row["target_host_ids_json"])):
                    invalid += 1
                elif mode == "jobs" and any(value not in job_ids for value in _safe_json_ids(row["target_job_ids_json"])):
                    invalid += 1
                elif mode == "repository" and row["target_repository_id"] is not None and int(row["target_repository_id"]) not in repository_ids:
                    invalid += 1
            result["schedule_rows_with_invalid_targets"] = invalid
        result["foreign_key_violations"] = len(connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall())
        result["freelist_pages"] = int(connection.exec_driver_sql("PRAGMA freelist_count").scalar() or 0)
        result["page_count"] = int(connection.exec_driver_sql("PRAGMA page_count").scalar() or 0)
        result["page_size"] = int(connection.exec_driver_sql("PRAGMA page_size").scalar() or 0)
    legacy_ssh_status = legacy_ssh_run_history_status(engine)
    result["legacy_ssh_run_rows"] = int(legacy_ssh_status.get("rows") or 0)
    result["legacy_ssh_run_logs"] = int(legacy_ssh_status.get("run_logs") or 0)
    result["sensitive_maintenance_backups"] = len(sensitive_maintenance_backup_paths())
    result["reclaimable_bytes_estimate"] = result["freelist_pages"] * result["page_size"]
    result["changes_available"] = bool(result["legacy_host_action_table"]) or any(int(result[key]) > 0 for key in (
        "stale_active_runs", "stale_mount_rows", "orphan_repository_access_rows",
        "orphan_host_action_rows", "legacy_host_action_rows", "legacy_ssh_run_rows",
        "legacy_ssh_run_logs", "sensitive_maintenance_backups", "orphan_notification_deliveries",
        "schedule_rows_with_invalid_targets",
        "freelist_pages",
    ))
    return result


def _create_safety_copy() -> Path:
    source_path = _database_path()
    MAINTENANCE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = MAINTENANCE_BACKUP_DIR / f"manager-before-cleanup-{_utcnow().strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    source = sqlite3.connect(source_path, timeout=60)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        # The live database may still contain deleted plaintext in freelist
        # pages until the deferred startup rebuild. Compact the offline safety
        # copy itself so retained rollback material never reintroduces it.
        target.execute("PRAGMA secure_delete=ON")
        target.execute("VACUUM")
        check = target.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise ValueError("Sicherheitskopie der Manager-Datenbank ist nicht konsistent")
    finally:
        target.close()
        source.close()
    destination.chmod(0o600)
    old = sorted(MAINTENANCE_BACKUP_DIR.glob("manager-before-cleanup-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    for item in old[5:]:
        item.unlink(missing_ok=True)
    return destination


def _create_security_safety_copy() -> Path:
    MAINTENANCE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = MAINTENANCE_BACKUP_DIR / f"security-before-cleanup-{_utcnow().strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    source = sqlite3.connect(SECURITY_DATABASE_PATH, timeout=60)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        check = target.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise ValueError("Sicherheitskopie der Security-Datenbank ist nicht konsistent")
    finally:
        target.close()
        source.close()
    destination.chmod(0o600)
    old = sorted(
        MAINTENANCE_BACKUP_DIR.glob("security-before-cleanup-*.sqlite3"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for item in old[5:]:
        item.unlink(missing_ok=True)
    return destination


def cleanup_manager_database(*, create_safety_copy: bool = True, vacuum: bool = True) -> dict[str, Any]:
    if engine.dialect.name != "sqlite":
        raise ValueError("Datenbankbereinigung wird nur für SQLite unterstützt")
    before = database_cleanup_preview()
    migration = migrate_legacy_host_ssh_actions(engine, sanitize=False)
    ssh_history_cleanup = sanitize_legacy_ssh_run_history(engine)
    sensitive_backups_removed = purge_sensitive_maintenance_backups()
    # The retained safety copy is created only after sensitive legacy SSH data
    # has been removed. Keeping a rollback copy with credentials would defeat
    # the purpose of the security cleanup.
    safety_copy = _create_safety_copy() if create_safety_copy else None
    security_safety_copy = (
        _create_security_safety_copy()
        if create_safety_copy and int(before.get("orphan_host_action_rows") or 0) > 0
        else None
    )
    now = _utcnow()
    stale_run_cutoff = _iso(now - timedelta(hours=24))
    orphan_delivery_cutoff = _iso(now - timedelta(days=30))
    counts = {
        "stale_runs_closed": 0,
        "stale_mount_rows_removed": 0,
        "orphan_repository_access_rows_removed": 0,
        "orphan_host_action_rows_removed": 0,
        "orphan_notification_deliveries_removed": 0,
        "schedule_rows_repaired": 0,
        "legacy_ssh_run_rows_sanitized": int(ssh_history_cleanup.get("rows_sanitized") or 0),
        "legacy_ssh_run_logs_removed": int(ssh_history_cleanup.get("run_logs_removed") or 0),
        "sensitive_maintenance_backups_removed": int(sensitive_backups_removed),
    }
    with engine.begin() as connection:
        tables = _table_names(connection)
        if "runs" in tables:
            cursor = connection.execute(text(
                "UPDATE runs SET status='failed', finished_at=:now, error=CASE WHEN COALESCE(error,'')='' THEN :message ELSE error || '\\n' || :message END "
                "WHERE status IN ('queued','running') AND created_at < :cutoff"
            ), {"now": _iso(now), "cutoff": stale_run_cutoff, "message": "Durch Datenbankbereinigung als veralteter unterbrochener Lauf abgeschlossen."})
            counts["stale_runs_closed"] = int(cursor.rowcount or 0)
        if "manager_archive_mounts" in tables:
            rows = connection.execute(text("SELECT id,mount_path,updated_at,created_at FROM manager_archive_mounts")).mappings().all()
            remove_ids = []
            cutoff = now - timedelta(minutes=10)
            for row in rows:
                timestamp = row.get("updated_at") or row.get("created_at")
                try:
                    dt = datetime.fromisoformat(str(timestamp))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    dt = datetime.min.replace(tzinfo=timezone.utc)
                if dt < cutoff and not archive_mount_is_active(str(row.get("mount_path") or "")):
                    remove_ids.append(int(row["id"]))
            if remove_ids:
                cursor = connection.execute(text("DELETE FROM manager_archive_mounts WHERE id IN (%s)" % ",".join(str(value) for value in remove_ids)))
                counts["stale_mount_rows_removed"] = int(cursor.rowcount or 0)
        if "host_repository_access" in tables:
            cursor = connection.execute(text(
                "DELETE FROM host_repository_access WHERE id IN (SELECT a.id FROM host_repository_access a LEFT JOIN hosts h ON h.id=a.host_id LEFT JOIN repositories r ON r.id=a.repository_id WHERE h.id IS NULL OR r.id IS NULL)"
            ))
            counts["orphan_repository_access_rows_removed"] = int(cursor.rowcount or 0)
        valid_host_ids = set(connection.execute(text("SELECT id FROM hosts")).scalars()) if "hosts" in tables else set()
        if "notification_deliveries" in tables and "runs" in tables:
            cursor = connection.execute(text(
                "DELETE FROM notification_deliveries WHERE id IN (SELECT d.id FROM notification_deliveries d LEFT JOIN runs r ON r.id=d.run_id WHERE d.run_id IS NOT NULL AND r.id IS NULL AND d.created_at < :cutoff)"
            ), {"cutoff": orphan_delivery_cutoff})
            counts["orphan_notification_deliveries_removed"] = int(cursor.rowcount or 0)
        if "backup_schedules" in tables:
            host_ids = set(connection.execute(text("SELECT id FROM hosts")).scalars()) if "hosts" in tables else set()
            job_ids = set(connection.execute(text("SELECT id FROM jobs")).scalars()) if "jobs" in tables else set()
            repository_ids = set(connection.execute(text("SELECT id FROM repositories")).scalars()) if "repositories" in tables else set()
            for row in connection.execute(text("SELECT id,target_mode,target_host_ids_json,target_job_ids_json,target_repository_id,enabled FROM backup_schedules")).mappings().all():
                mode = str(row["target_mode"] or "")
                host_targets = [value for value in _safe_json_ids(row["target_host_ids_json"]) if value in host_ids]
                job_targets = [value for value in _safe_json_ids(row["target_job_ids_json"]) if value in job_ids]
                repository_id = int(row["target_repository_id"]) if row["target_repository_id"] is not None else None
                enabled = bool(row["enabled"])
                changed = False
                if mode == "hosts" and host_targets != _safe_json_ids(row["target_host_ids_json"]):
                    changed = True
                    if not host_targets:
                        enabled = False
                elif mode == "jobs" and job_targets != _safe_json_ids(row["target_job_ids_json"]):
                    changed = True
                    if not job_targets:
                        enabled = False
                elif mode == "repository" and repository_id not in repository_ids:
                    repository_id = None
                    enabled = False
                    changed = True
                if changed:
                    connection.execute(text(
                        "UPDATE backup_schedules SET target_host_ids_json=:hosts,target_job_ids_json=:jobs,target_repository_id=:repo,enabled=:enabled,updated_at=:updated WHERE id=:id"
                    ), {"hosts": json.dumps(host_targets), "jobs": json.dumps(job_targets), "repo": repository_id, "enabled": int(enabled), "updated": _iso(now), "id": int(row["id"])})
                    counts["schedule_rows_repaired"] += 1
        connection.exec_driver_sql("PRAGMA optimize")
    counts["orphan_host_action_rows_removed"] = delete_orphan_host_ssh_actions(valid_host_ids)
    vacuumed = False
    vacuum_deferred = False
    if vacuum:
        # VACUUM requires an exclusive SQLite lock. Running it while the web UI
        # continues polling caused every concurrent API read to fail with
        # "database is locked". Schedule the rebuild for the next application
        # startup, before HTTP requests are accepted.
        mark_manager_vacuum_pending()
        vacuum_deferred = True
    after = database_cleanup_preview()
    return {
        "before": before,
        "after": after,
        "counts": counts,
        "safety_copy": str(safety_copy) if safety_copy else None,
        "security_safety_copy": str(security_safety_copy) if security_safety_copy else None,
        "migration": migration,
        "ssh_history_cleanup": ssh_history_cleanup,
        "vacuumed": vacuumed,
        "vacuum_deferred": vacuum_deferred,
        "restart_required": vacuum_deferred,
    }
