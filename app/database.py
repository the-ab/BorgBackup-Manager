from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL, ensure_data_dir


ensure_data_dir()
_is_sqlite = DATABASE_URL.startswith("sqlite")
_is_memory_sqlite = DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}
connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if _is_memory_sqlite:
    engine_options["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **engine_options)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            if not _is_memory_sqlite:
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).casefold():
                        raise
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA secure_delete=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def migrate_schema(target_engine=engine) -> None:
    """Apply additive SQLite-compatible migrations for existing installations."""
    additions = {
        "hosts": {
            "host_key": "TEXT",
            "repository_ready": "BOOLEAN NOT NULL DEFAULT 0",
            "borg_version": "VARCHAR(40)",
            "borg_version_status": "VARCHAR(20)",
            "borg_checked_at": "DATETIME",
        },
        "repositories": {
            "enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "encryption_mode": "VARCHAR(40) NOT NULL DEFAULT 'repokey-blake2'",
            "storage_path": "VARCHAR(500)",
            "initialized": "BOOLEAN NOT NULL DEFAULT 0",
            "size_bytes": "INTEGER",
            "original_size_bytes": "INTEGER",
            "compressed_size_bytes": "INTEGER",
            "deduplicated_size_bytes": "INTEGER",
            "size_checked_at": "DATETIME",
            "external_ssh_public_key": "TEXT",
            "external_host_fingerprint": "VARCHAR(120)",
            "validation_error": "TEXT",
            "validation_details": "TEXT",
            "validated_at": "DATETIME",
            "storage_guard_enabled": "BOOLEAN",
            "storage_guard_threshold_percent": "INTEGER",
            "external_storage_total_bytes": "INTEGER",
            "external_storage_used_bytes": "INTEGER",
            "external_storage_free_bytes": "INTEGER",
            "external_storage_usage_percent": "FLOAT",
            "external_storage_path": "VARCHAR(500)",
            "external_storage_checked_at": "DATETIME",
            "external_storage_error": "TEXT",
        },
        "jobs": {
            "archive_prefix": "VARCHAR(80)",
            "archive_prefix_history_json": "TEXT NOT NULL DEFAULT '[]'",
            "create_options_json": "TEXT NOT NULL DEFAULT '{}'",
            "source_size_bytes": "INTEGER",
            "source_file_count": "INTEGER",
            "source_stats_checked_at": "DATETIME",
            "source_stats_origin": "VARCHAR(20)",
            "source_stats_detail_json": "TEXT NOT NULL DEFAULT '{}'",
            "manual_prune_after_backup": "BOOLEAN NOT NULL DEFAULT 0",
            "manual_compact_after_prune": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "backup_schedules": {
            "parallel_limit": "INTEGER NOT NULL DEFAULT 0",
        },
        "runs": {
            "repository_id": "INTEGER",
            "job_name_snapshot": "VARCHAR(100)",
            "log_output": "TEXT NOT NULL DEFAULT ''",
            "warning_summary_json": "TEXT NOT NULL DEFAULT ''",
            "borg_version": "VARCHAR(40)",
            "trigger_type": "VARCHAR(20) NOT NULL DEFAULT 'manual'",
            "schedule_name_snapshot": "VARCHAR(100)",
            "schedule_id_snapshot": "INTEGER",
            "schedule_parallel_limit_snapshot": "INTEGER NOT NULL DEFAULT 0",
            "archive_name_snapshot": "VARCHAR(300)",
            "backup_original_size_bytes": "INTEGER",
            "backup_compressed_size_bytes": "INTEGER",
            "backup_deduplicated_size_bytes": "INTEGER",
            "backup_file_count": "INTEGER",
            "backup_source_size_bytes_snapshot": "INTEGER",
            "backup_source_file_count_snapshot": "INTEGER",
            "backup_network_download_bytes": "INTEGER",
            "backup_network_upload_bytes": "INTEGER",
            "restore_total_size_bytes": "INTEGER",
            "restore_processed_size_bytes": "INTEGER",
            "restore_total_file_count": "INTEGER",
            "restore_processed_file_count": "INTEGER",
        },
    }
    with target_engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table, columns in additions.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
