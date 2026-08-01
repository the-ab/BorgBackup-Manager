from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.database import migrate_schema


def test_supported_v110_database_receives_current_additive_columns():
    supported_engine = create_engine("sqlite://")
    with supported_engine.begin() as connection:
        connection.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, name VARCHAR(100), host_key TEXT, repository_ready BOOLEAN NOT NULL DEFAULT 0)"))
        connection.execute(text("CREATE TABLE repositories (id INTEGER PRIMARY KEY, name VARCHAR(100), encryption_mode VARCHAR(40), storage_path VARCHAR(500), initialized BOOLEAN NOT NULL DEFAULT 0)"))
        connection.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, name VARCHAR(100), archive_prefix VARCHAR(80), archive_prefix_history_json TEXT NOT NULL DEFAULT '[]', create_options_json TEXT NOT NULL DEFAULT '{}')"))
        connection.execute(text("CREATE TABLE backup_schedules (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        connection.execute(text("CREATE TABLE runs (id INTEGER PRIMARY KEY, action VARCHAR(30), repository_id INTEGER, log_output TEXT NOT NULL DEFAULT '')"))

    migrate_schema(supported_engine)

    inspector = inspect(supported_engine)
    host_columns = {column["name"] for column in inspector.get_columns("hosts")}
    repository_columns = {column["name"] for column in inspector.get_columns("repositories")}
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    schedule_columns = {column["name"] for column in inspector.get_columns("backup_schedules")}
    run_columns = {column["name"] for column in inspector.get_columns("runs")}

    assert {"borg_version", "borg_version_status", "borg_checked_at"} <= host_columns
    assert {
        "enabled", "external_ssh_public_key", "external_host_fingerprint",
        "validation_error", "validation_details", "validated_at",
        "storage_guard_enabled", "storage_guard_threshold_percent",
        "external_storage_total_bytes", "external_storage_used_bytes",
        "external_storage_free_bytes", "external_storage_usage_percent",
        "external_storage_path", "external_storage_checked_at", "external_storage_error",
    } <= repository_columns
    assert {
        "source_size_bytes", "source_file_count", "source_stats_checked_at",
        "source_stats_origin", "source_stats_detail_json",
        "manual_prune_after_backup", "manual_compact_after_prune",
    } <= job_columns
    assert {"parallel_limit"} <= schedule_columns
    assert {
        "job_name_snapshot", "warning_summary_json", "borg_version",
        "trigger_type", "schedule_name_snapshot", "schedule_id_snapshot",
        "schedule_parallel_limit_snapshot", "archive_name_snapshot",
        "backup_original_size_bytes", "backup_compressed_size_bytes",
        "backup_deduplicated_size_bytes", "backup_file_count",
        "backup_source_size_bytes_snapshot", "backup_source_file_count_snapshot",
        "backup_network_download_bytes", "backup_network_upload_bytes",
    } <= run_columns
