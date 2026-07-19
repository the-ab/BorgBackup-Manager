from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.schedules import normalize_schedule, schedule_expressions
from app import security_store


def test_multiple_schedule_expressions_are_normalized_and_deduplicated():
    value = "0 2 * * *\n30 14 * * mon-fri;0 2 * * *"
    assert schedule_expressions(value) == ["0 2 * * *", "30 14 * * mon-fri"]
    assert normalize_schedule(value) == "0 2 * * *;30 14 * * mon-fri"


def test_invalid_or_excessive_schedules_are_rejected():
    with pytest.raises(ValueError):
        schedule_expressions("not a cron expression")
    with pytest.raises(ValueError):
        schedule_expressions(";".join(f"{minute} * * * *" for minute in range(25)))


def test_passwords_are_scrypt_hashes_and_not_reversible():
    encoded = security_store.hash_password("Strong-Test-Password-2026!")
    assert encoded.startswith("scrypt$")
    assert "Strong-Test-Password-2026!" not in encoded
    assert security_store.verify_password("Strong-Test-Password-2026!", encoded)
    assert not security_store.verify_password("Wrong-Test-Password-2026!", encoded)


def test_generated_initial_admin_password_always_meets_policy(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", security_dir / "master.key")
    monkeypatch.setattr(security_store.secrets, "token_urlsafe", lambda _length: "onlylowercaseletters")

    result = security_store.initialize_security_store(None)
    password = security_store.get_secret("bootstrap", "initial_admin_password")

    assert result["created"] is True
    assert password == "Aa1!onlylowercaseletters"
    security_store.validate_password(password)
    with sqlite3.connect(database) as connection:
        encoded = connection.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
    assert security_store.verify_password(password, encoded)


def test_security_database_permissions_are_restricted(monkeypatch, tmp_path: Path):
    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    initial = security_dir / "initial-admin.txt"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", initial)

    result = security_store.initialize_security_store(None)
    assert result["created"] is True
    assert database.stat().st_mode & 0o777 == 0o600
    assert security_dir.stat().st_mode & 0o777 == 0o700
    with sqlite3.connect(database) as connection:
        password_hash = connection.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        assert password_hash.startswith("scrypt$")


def test_last_administrator_cannot_be_deleted(monkeypatch, tmp_path: Path):
    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    initial = security_dir / "initial-admin.txt"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", initial)

    security_store.initialize_security_store(None)
    with sqlite3.connect(database) as connection:
        administrator_id = int(connection.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0])
    with pytest.raises(ValueError, match="letzte Administrator"):
        security_store.delete_user(administrator_id, current_user_id=administrator_id + 100)


def test_disabled_administrator_can_only_be_deleted_when_another_admin_exists(monkeypatch, tmp_path: Path):
    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    initial = security_dir / "initial-admin.txt"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", initial)

    security_store.initialize_security_store(None)
    second = security_store.create_user("second-admin", "Second-Admin-Password-2026!", "admin", False)
    security_store.update_user(second["id"], "second-admin", "admin", False)
    security_store.delete_user(second["id"], current_user_id=9999)
    status = security_store.security_status()
    assert status["administrators"] == 1
    assert status["active_administrators"] == 1


def test_initial_admin_password_is_encrypted_in_security_database(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    old_file = security_dir / "initial-admin.txt"
    master_key = security_dir / "master.key"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", old_file)
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", master_key)

    result = security_store.initialize_security_store(None)

    assert result["created"] is True
    assert not old_file.exists()
    with sqlite3.connect(database) as connection:
        encrypted = connection.execute(
            "SELECT encrypted_value FROM secrets WHERE scope='bootstrap' AND name='initial_admin_password'"
        ).fetchone()[0]
    assert encrypted.startswith("v2:")
    assert "initial_admin_password" not in encrypted
    assert master_key.stat().st_mode & 0o777 == 0o600


def test_legacy_job_cron_is_migrated_to_central_schedule(monkeypatch):
    import json
    from uuid import uuid4

    from app.database import Base, SessionLocal, engine
    from app.models import BackupSchedule, Host, Job, Repository
    from app.schedules import migrate_legacy_job_schedules, schedule_target_job_ids

    Base.metadata.create_all(engine)
    marker = uuid4().hex
    with SessionLocal() as db:
        host = Host(name=f"legacy-host-{marker}", address="127.0.0.1", username="root")
        repository = Repository(name=f"legacy-repo-{marker}", location=f"/tmp/{marker}", initialized=True)
        db.add_all([host, repository]); db.flush()
        job = Job(
            name=f"legacy-job-{marker}", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv"]', exclude_patterns_json="[]", create_options_json="{}",
            schedule="0 2 * * *;30 14 * * mon-fri", enabled=True,
        )
        db.add(job); db.commit(); job_id = job.id

    with SessionLocal() as db:
        assert migrate_legacy_job_schedules(db) == 1
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        schedule = db.query(BackupSchedule).filter(BackupSchedule.target_job_ids_json == json.dumps([job_id])).one()
        assert job.schedule is None
        assert schedule.expressions == "0 2 * * *;30 14 * * mon-fri"
        assert schedule_target_job_ids(db, schedule) == [job_id]


def test_local_account_recovery_unlocks_and_resets_admin(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    initial = security_dir / "initial-admin.txt"
    master_key = security_dir / "master.key"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", initial)
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", master_key)

    security_store.initialize_security_store("Old-Admin-Token-2026!")
    for _ in range(5):
        security_store.authenticate_user("admin", "wrong-password")
    before = security_store.authentication_readiness()
    assert before["ready"] is True
    # Failed logins are rate-limited per source instead of locking the whole account.
    assert before["locked_administrators"] == 0

    password = security_store.recover_account("admin", make_admin=True)
    assert security_store.authenticate_user("admin", password) is not None
    after = security_store.authentication_readiness()
    assert after["ready"] is True
    assert after["locked_administrators"] == 0


def test_authentication_readiness_rejects_invalid_password_hash(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", security_dir / "master.key")
    security_store.initialize_security_store("Old-Admin-Token-2026!")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE users SET password_hash='broken' WHERE username='admin'")
        connection.commit()
    status = security_store.authentication_readiness()
    assert status["ready"] is False
    assert status["invalid_password_hashes"] == 1


@pytest.mark.asyncio
async def test_scheduled_backup_refreshes_repository_size_once_after_schedule(monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app import service
    from app.database import Base, SessionLocal, engine
    from app.models import Host, Job, Repository

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        host = Host(name=f"scheduled-host-{suffix}", address="127.0.0.1", username="root", host_key="key")
        repository = Repository(name=f"scheduled-repo-{suffix}", location=f"/tmp/{suffix}", initialized=True)
        db.add_all([host, repository]); db.flush()
        job = Job(
            name=f"scheduled-job-{suffix}", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv"]', prune_options_json=json.dumps({"daily": 7}),
        )
        db.add(job); db.commit()
        job_id, repository_id = job.id, repository.id

    queued = []
    run_ids = iter([101, 102, 103])
    refreshed = []

    def queue(job_id_arg, action, restore=None, *, refresh_size_after=True, trigger_type="manual", schedule_name=None):
        queued.append((job_id_arg, action, refresh_size_after, trigger_type, schedule_name))
        return next(run_ids)

    async def wait(_run_id):
        return "success"

    async def refresh(repository_id_arg):
        refreshed.append(repository_id_arg)
        return {}

    monkeypatch.setattr(service, "queue_job_action", queue)
    monkeypatch.setattr(service, "_wait_for_run", wait)
    monkeypatch.setattr(service, "refresh_repository_statistics", refresh)
    monkeypatch.setattr(service, "load_settings", lambda: SimpleNamespace(
        repository_size_after_run=True, compact_after_prune=True,
    ))

    await service.scheduled_backup(job_id, "Nachtlauf")

    assert queued == [
        (job_id, "backup", False, "schedule", "Nachtlauf"),
        (job_id, "prune", False, "schedule", "Nachtlauf"),
        (job_id, "compact", False, "schedule", "Nachtlauf"),
    ]
    assert refreshed == [repository_id]
