from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.database import migrate_schema


def test_legacy_database_receives_additive_columns():
    legacy_engine = create_engine("sqlite://")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        connection.execute(text("CREATE TABLE repositories (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        connection.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        connection.execute(text("CREATE TABLE runs (id INTEGER PRIMARY KEY, action VARCHAR(30))"))

    migrate_schema(legacy_engine)

    inspector = inspect(legacy_engine)
    host_columns = {column["name"] for column in inspector.get_columns("hosts")}
    repository_columns = {column["name"] for column in inspector.get_columns("repositories")}
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    assert {"host_key", "repository_ready"} <= host_columns
    assert {
        "encrypted_passphrase", "encryption_mode", "encrypted_keyfile", "storage_path", "initialized",
        "size_bytes", "original_size_bytes", "compressed_size_bytes", "deduplicated_size_bytes",
        "size_checked_at", "access_host_id", "external_ssh_key_path", "external_known_hosts_path",
        "encrypted_external_ssh_key", "external_ssh_public_key", "encrypted_external_known_hosts",
        "external_host_fingerprint", "validation_error", "validation_details", "validated_at",
        "storage_guard_enabled", "storage_guard_threshold_percent",
    } <= repository_columns
    assert {"archive_prefix", "archive_prefix_history_json", "create_options_json", "source_size_bytes", "source_file_count", "source_stats_checked_at", "source_stats_origin"} <= job_columns
    assert {"repository_id", "job_name_snapshot", "log_output", "warning_summary_json", "borg_version", "trigger_type", "schedule_name_snapshot", "archive_name_snapshot", "backup_original_size_bytes", "backup_compressed_size_bytes", "backup_deduplicated_size_bytes", "backup_file_count"} <= run_columns
