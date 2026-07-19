from __future__ import annotations

import json
import sqlite3
import zipfile

import pytest
from pathlib import Path

from app import backups, settings
from app.repository_sizes import directory_size
from app.schemas import SettingsIn


def test_settings_are_atomic_and_validated(monkeypatch, tmp_path: Path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    configured = SettingsIn(
        dashboard_recent_runs_limit=25,
        runs_list_limit=50,
        auto_refresh_seconds=30,
        list_max_height=640,
        density="compact",
        appearance="dark",
        repository_size_after_run=False,
    )

    settings.save_settings(configured)
    loaded = settings.load_settings()

    assert loaded == configured
    assert json.loads(path.read_text(encoding="utf-8"))["density"] == "compact"
    assert not path.with_suffix(".tmp").exists()


def test_existing_settings_receive_default_exclusion_template(monkeypatch, tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"density":"compact"}', encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)

    loaded = settings.load_settings()

    assert loaded.density == "compact"
    assert loaded.exclude_templates[0].name == "Linux-Systempfade"
    assert "/proc" in loaded.exclude_templates[0].patterns


def test_repository_directory_size_does_not_follow_symlinks(tmp_path: Path):
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "data").write_bytes(b"12345")
    outside = tmp_path.parent / "outside-size-test"
    outside.write_bytes(b"x" * 100)
    try:
        (tmp_path / "outside-link").symlink_to(outside)
    except OSError:
        pass

    assert directory_size(tmp_path) == 5
    outside.unlink(missing_ok=True)


def test_full_backup_contains_snapshot_manifest_and_keys(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    database = data / "manager.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sample(value TEXT)")
    connection.execute("INSERT INTO sample VALUES ('saved')")
    connection.commit(); connection.close()
    (data / "ssh").mkdir(); (data / "ssh" / "id_ed25519").write_text("private", encoding="utf-8")
    (data / "settings.json").write_text('{"density":"compact"}', encoding="utf-8")
    (data / "notifications.json").write_text('{"enabled":true}', encoding="utf-8")
    monkeypatch.setattr(backups, "DATA_DIR", data)
    monkeypatch.setattr(backups, "BACKUP_DIR", data / "backups")
    monkeypatch.setattr(backups, "SETTINGS_PATH", data / "settings.json")
    monkeypatch.setattr(backups, "NOTIFICATION_SETTINGS_PATH", data / "notifications.json")
    security_dir = data / "security"
    security_dir.mkdir()
    security_database = security_dir / "security.db"
    security_connection = sqlite3.connect(security_database)
    security_connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    security_connection.execute("CREATE TABLE sessions(id INTEGER PRIMARY KEY, token_hash TEXT)")
    security_connection.execute("INSERT INTO users(username) VALUES ('admin')")
    security_connection.execute("INSERT INTO sessions(token_hash) VALUES ('must-not-be-restored')")
    security_connection.commit(); security_connection.close()
    (security_dir / "master.key").write_text("test-master-key", encoding="utf-8")
    monkeypatch.setattr(backups, "DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(backups, "SECURITY_DATABASE_PATH", security_database)
    monkeypatch.setenv("BBM_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("BBM_SECRET_KEY", "crypto-secret")

    passphrase = "Serverwechsel-Backup-2026!"
    result = backups.create_full_backup("0.5.0", "serverwechsel", passphrase)
    assert result.suffix == ".bbm"

    with backups.plain_backup_file(result, passphrase) as plain_backup:
        with zipfile.ZipFile(plain_backup) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            migration = archive.read("migration.env").decode()
    assert manifest["format"] == backups.BACKUP_FORMAT
    assert manifest["repository_data_included"] is False
    assert {
        "data/manager.db", "data/settings.json", "data/notifications.json",
        "data/security/security.db", "data/security/master.key",
    } <= names
    assert "data/ssh/id_ed25519" not in names
    assert "BBM_ADMIN_TOKEN" not in migration
    assert "BBM_SECRET_KEY" not in migration
    restored_security = tmp_path / "security-from-backup.db"
    with backups.plain_backup_file(result, passphrase) as plain_backup:
        with zipfile.ZipFile(plain_backup) as archive:
            restored_security.write_bytes(archive.read("data/security/security.db"))
    with sqlite3.connect(restored_security) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_managed_repository_location_is_refreshed_after_endpoint_change(monkeypatch):
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import Repository

    with SessionLocal() as db:
        row = Repository(
            name="moved-managed-repository",
            location="ssh://borg@old.example:2222/./moved-12345678",
            storage_path="/repositories/moved-12345678",
            initialized=True,
            extra_env_json="{}",
        )
        db.add(row)
        db.commit()
        row_id = row.id

    monkeypatch.setattr(main_module, "REPOSITORY_PUBLIC_HOST", "new.example")
    monkeypatch.setattr(main_module, "REPOSITORY_SSH_PORT", 2200)
    main_module.sync_managed_repository_locations()

    with SessionLocal() as db:
        refreshed = db.get(Repository, row_id)
        assert refreshed.location == "ssh://borg@new.example:2200/./moved-12345678"


def test_run_history_cleanup_removes_only_old_finished_runs(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import app.main as main_module
    from app.database import Base, SessionLocal, engine
    from app.models import Run
    from app.schemas import SettingsIn

    Base.metadata.create_all(engine)
    marker = uuid4().hex
    old = datetime.now(timezone.utc) - timedelta(days=120)
    with SessionLocal() as db:
        finished = Run(action=f"finished-{marker}", status="success", created_at=old)
        active = Run(action=f"active-{marker}", status="running", created_at=old)
        recent = Run(action=f"recent-{marker}", status="success")
        db.add_all([finished, active, recent])
        db.commit()
        finished_id, active_id, recent_id = finished.id, active.id, recent.id

    monkeypatch.setattr(main_module, "load_settings", lambda: SettingsIn(run_retention_days=90))
    removed = main_module.cleanup_run_history()

    assert removed >= 1
    with SessionLocal() as db:
        assert db.get(Run, finished_id) is None
        assert db.get(Run, active_id) is not None
        assert db.get(Run, recent_id) is not None


def test_run_history_cleanup_removes_matching_log_file(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import app.main as main_module
    import app.run_logs as run_logs
    from app.database import Base, SessionLocal, engine
    from app.models import Run
    from app.schemas import SettingsIn

    Base.metadata.create_all(engine)
    marker = uuid4().hex
    old = datetime.now(timezone.utc) - timedelta(days=120)
    with SessionLocal() as db:
        row = Run(action=f"log-cleanup-{marker}", status="success", created_at=old)
        db.add(row); db.commit(); run_id = row.id

    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(main_module, "delete_run_log", run_logs.delete_run_log)
    path = run_logs.run_log_path(run_id)
    path.write_text("test log", encoding="utf-8")
    monkeypatch.setattr(main_module, "load_settings", lambda: SettingsIn(run_retention_days=90))

    assert main_module.cleanup_run_history() >= 1
    assert not path.exists()


def test_invalid_stored_borg_version_is_reset():
    from uuid import uuid4

    import app.main as main_module
    from app.database import Base, SessionLocal, engine
    from app.models import Host

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        row = Host(
            name=f"invalid-version-{uuid4().hex}", address="127.0.0.1", port=22, username="root",
            borg_version="1.02.1", borg_version_status="critical",
        )
        db.add(row); db.commit(); host_id = row.id

    assert main_module.repair_invalid_stored_borg_versions() >= 1
    with SessionLocal() as db:
        row = db.get(Host, host_id)
        assert row.borg_version is None
        assert row.borg_version_status == "unknown"


def test_encrypted_manager_backup_roundtrip_and_wrong_passphrase(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    database = data / "manager.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sample(value TEXT)")
    connection.execute("INSERT INTO sample VALUES ('encrypted')")
    connection.commit(); connection.close()
    (data / "settings.json").write_text('{"density":"compact"}', encoding="utf-8")
    (data / "ssh").mkdir()
    (data / "ssh" / "id_ed25519").write_text("private", encoding="utf-8")
    monkeypatch.setattr(backups, "DATA_DIR", data)
    monkeypatch.setattr(backups, "BACKUP_DIR", data / "backups")
    monkeypatch.setattr(backups, "SETTINGS_PATH", data / "settings.json")
    monkeypatch.setattr(backups, "DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("BBM_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("BBM_SECRET_KEY", "crypto-secret")

    result = backups.create_full_backup("0.8.8", "verschluesselt", "correct horse")

    assert result.suffix == ".bbm"
    listed = backups.list_full_backups()
    assert listed[0]["encrypted"] is True
    assert listed[0]["manifest"]["app_version"] == "0.8.8"
    try:
        backups.prepare_full_backup_restore(result, "wrong passphrase")
    except ValueError as exc:
        assert "falsch" in str(exc)
    else:
        raise AssertionError("wrong passphrase was accepted")
    staging, manifest = backups.prepare_full_backup_restore(result, "correct horse")
    assert manifest["format"] == backups.BACKUP_FORMAT
    assert (staging / "data" / "manager.db").is_file()


def test_controller_key_rotation_archives_previous_pair(monkeypatch):
    from app import service

    stored = {
        "controller_private_key": "old-private",
        "controller_public_key": "ssh-ed25519 OLD old",
    }

    monkeypatch.setattr(service, "get_system_secret", lambda name, default=None: stored.get(name, default))
    monkeypatch.setattr(service, "set_system_secret", lambda name, value: stored.__setitem__(name, value))
    monkeypatch.setattr(
        service, "generate_ed25519_keypair",
        lambda _comment: ("new-private", "ssh-ed25519 NEW new"),
    )

    public = service.rotate_controller_key()

    assert public == "ssh-ed25519 NEW new"
    assert stored["controller_private_key"] == "new-private"
    assert stored["controller_public_key"] == "ssh-ed25519 NEW new"
    assert any(name.startswith("controller_private_key_archive_") for name in stored)
    assert any(name.startswith("controller_public_key_archive_") for name in stored)


def test_prepared_restore_replaces_control_data_and_removes_sqlite_sidecars(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "manager.db").write_text("old-db", encoding="utf-8")
    (data / "manager.db-wal").write_text("wal", encoding="utf-8")
    (data / "manager.db-shm").write_text("shm", encoding="utf-8")
    (data / "backups").mkdir()
    (data / "backups" / "keep.zip").write_text("keep", encoding="utf-8")
    (data / "notifications.json").write_text("{\"enabled\":true}", encoding="utf-8")
    staging = tmp_path / "stage"
    (staging / "data" / "ssh").mkdir(parents=True)
    (staging / "data" / "manager.db").write_text("new-db", encoding="utf-8")
    (staging / "data" / "settings.json").write_text('{"density":"compact"}', encoding="utf-8")
    (staging / "data" / "ssh" / "id_ed25519").write_text("new-key", encoding="utf-8")
    monkeypatch.setattr(backups, "DATA_DIR", data)

    backups.apply_prepared_restore(staging)

    assert (data / "manager.db").read_text(encoding="utf-8") == "new-db"
    assert not (data / "manager.db-wal").exists()
    assert not (data / "manager.db-shm").exists()
    assert (data / "ssh" / "id_ed25519").read_text(encoding="utf-8") == "new-key"
    assert not (data / "notifications.json").exists()
    assert (data / "backups" / "keep.zip").is_file()


def test_uploaded_encrypted_backup_is_validated_and_stored_without_overwrite(monkeypatch, tmp_path: Path):
    import base64
    import json
    import os
    import struct

    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    backup_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(backups, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backups, "DATA_DIR", data_dir)

    name = "borgbackup-manager-backup-v1.0.42-20260719-120000-upload.bbm"
    source = tmp_path / "incoming"
    header = {
        "format": backups.BACKUP_ENVELOPE_FORMAT,
        "format_version": 1,
        "app_version": "1.0.42",
        "created_at": "2026-07-19T12:00:00+00:00",
        "label": "upload",
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt-n32768-r8-p1",
        "salt": base64.b64encode(b"s" * 16).decode("ascii"),
        "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    source.write_bytes(backups.BACKUP_MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes + b"x" * 17)

    result = backups.store_uploaded_backup(source, name)
    stored = backup_dir / name
    assert result["name"] == name
    assert result["encrypted"] is True
    assert stored.is_file()
    assert not source.exists()
    assert os.stat(stored).st_mode & 0o777 == 0o600

    duplicate = tmp_path / "duplicate"
    duplicate.write_bytes(stored.read_bytes())
    with pytest.raises(FileExistsError):
        backups.store_uploaded_backup(duplicate, name)
    assert duplicate.is_file()
