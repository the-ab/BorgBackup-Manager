from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import engine
from app.security_store import (
    delete_secret,
    import_legacy_host_ssh_actions,
    secret_exists,
    set_secret,
)
from app.sqlite_maintenance import (
    mark_manager_vacuum_pending,
    retry_sqlite,
    sanitize_sqlite_database,
    sqlite_database_path,
)

_MIGRATION_SCOPE = "migration"
_PENDING_NAME = "host_ssh_actions_manager_vacuum_pending"
_COMPLETE_NAME = "host_ssh_actions_security_store_complete"


def legacy_host_ssh_action_status(target_engine: Engine = engine) -> dict[str, Any]:
    if target_engine.dialect.name != "sqlite":
        return {"supported": False, "table_present": False, "rows": 0}

    def inspect_source() -> dict[str, Any]:
        with target_engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if "host_ssh_actions" not in tables:
                return {"supported": True, "table_present": False, "rows": 0}
            columns = {column["name"] for column in inspect(connection).get_columns("host_ssh_actions")}
            required = {"id", "host_id", "name", "command", "timeout_seconds", "enabled"}
            if not required.issubset(columns):
                raise ValueError("Die alte SSH-Aktionstabelle besitzt ein unbekanntes Schema")
            rows = int(connection.execute(text("SELECT COUNT(*) FROM host_ssh_actions")).scalar() or 0)
            return {"supported": True, "table_present": True, "rows": rows}

    return retry_sqlite(inspect_source)


def _read_legacy_rows(target_engine: Engine) -> tuple[bool, list[dict[str, Any]]]:
    def read_rows() -> tuple[bool, list[dict[str, Any]]]:
        with target_engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if "host_ssh_actions" not in tables:
                return False, []
            columns = {column["name"] for column in inspect(connection).get_columns("host_ssh_actions")}
            required = {
                "id", "host_id", "name", "command", "timeout_seconds", "enabled",
                "created_at", "updated_at",
            }
            if not required.issubset(columns):
                missing = ", ".join(sorted(required - columns))
                raise ValueError(f"Die alte SSH-Aktionstabelle ist unvollständig: {missing}")
            rows = [dict(row) for row in connection.execute(text(
                """
                SELECT id,host_id,name,command,timeout_seconds,enabled,created_at,updated_at
                  FROM host_ssh_actions
                 ORDER BY id
                """
            )).mappings().all()]
            return True, rows
    return retry_sqlite(read_rows)


def _drop_legacy_table(target_engine: Engine) -> None:
    def drop_table() -> None:
        with target_engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS host_ssh_actions"))
    retry_sqlite(drop_table, attempts=10, delay_seconds=0.35)


def migrate_legacy_host_ssh_actions(
    target_engine: Engine = engine, *, sanitize: bool = True,
) -> dict[str, Any]:
    """Move legacy plaintext SSH actions from manager.db into security.db.

    Every source row is encrypted and verified before the manager.db table is
    removed. The destructive source cleanup is retried for transient SQLite
    locks. A persistent marker survives interruptions between DROP TABLE and
    the final checkpoint/VACUUM pass.
    """
    if target_engine.dialect.name != "sqlite":
        return {
            "supported": False, "migrated": 0, "table_removed": False,
            "vacuumed": False, "vacuum_pending": False,
        }

    has_legacy_table, rows = _read_legacy_rows(target_engine)
    migrated = import_legacy_host_ssh_actions(rows) if rows else 0
    table_removed = False

    if has_legacy_table:
        # Set the marker before dropping the source. A crash after DROP TABLE
        # therefore cannot skip the later sanitization pass.
        set_secret(_MIGRATION_SCOPE, _PENDING_NAME, "1")
        mark_manager_vacuum_pending()
        _drop_legacy_table(target_engine)
        table_removed = True

    status_after_drop = legacy_host_ssh_action_status(target_engine)
    if status_after_drop["table_present"]:
        raise RuntimeError("Die Klartexttabelle host_ssh_actions konnte nicht entfernt werden")

    pending_vacuum = secret_exists(_MIGRATION_SCOPE, _PENDING_NAME)
    vacuumed = False
    if pending_vacuum and sanitize:
        result = sanitize_sqlite_database(target_engine)
        vacuumed = bool(result.get("vacuumed"))
        if vacuumed:
            database_path = sqlite_database_path(target_engine)
            if database_path is not None and rows:
                candidates = (
                    database_path,
                    database_path.with_name(database_path.name + "-wal"),
                    database_path.with_name(database_path.name + "-shm"),
                )
                for source in rows:
                    plaintext = str(source["command"]).encode("utf-8")
                    if not plaintext:
                        continue
                    for candidate in candidates:
                        if candidate.is_file() and plaintext in candidate.read_bytes():
                            raise RuntimeError(
                                f"Klartextrest der SSH-Aktion #{source['id']} in {candidate.name} erkannt"
                            )
            delete_secret(_MIGRATION_SCOPE, _PENDING_NAME)
            set_secret(_MIGRATION_SCOPE, _COMPLETE_NAME, "1")
            pending_vacuum = False

    return {
        "supported": True,
        "migrated": migrated,
        "table_removed": table_removed,
        "vacuumed": vacuumed,
        "vacuum_pending": pending_vacuum,
    }
