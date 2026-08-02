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


def test_incomplete_existing_security_database_is_rejected_without_schema_completion(monkeypatch, tmp_path: Path):
    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    security_dir.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        connection.commit()
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")

    with pytest.raises(RuntimeError, match="älter als die unterstützte Baseline"):
        security_store.initialize_security_store()

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables == {"users"}


def test_existing_v135_security_database_with_unknown_table_is_normalized(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", security_dir / "master.key")
    security_store.initialize_security_store()
    with sqlite3.connect(database) as connection:
        user = connection.execute("SELECT id,username,password_hash FROM users ORDER BY id LIMIT 1").fetchone()
        connection.execute("CREATE TABLE obsolete_transition_state (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO obsolete_transition_state(id,note) VALUES(1,'legacy')")
        connection.commit()

    result = security_store.initialize_security_store()

    assert result["baseline_backup"]
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        restored = connection.execute("SELECT id,username,password_hash FROM users ORDER BY id LIMIT 1").fetchone()
    assert "obsolete_transition_state" not in tables
    assert restored == user


def test_generated_initial_admin_password_always_meets_policy(monkeypatch, tmp_path: Path):
    from app import secret_crypto

    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", security_dir / "master.key")
    monkeypatch.setattr(security_store.secrets, "token_urlsafe", lambda _length: "onlylowercaseletters")

    result = security_store.initialize_security_store()
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

    result = security_store.initialize_security_store()
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

    security_store.initialize_security_store()
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

    security_store.initialize_security_store()
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

    result = security_store.initialize_security_store()

    assert result["created"] is True
    assert not old_file.exists()
    with sqlite3.connect(database) as connection:
        encrypted = connection.execute(
            "SELECT encrypted_value FROM secrets WHERE scope='bootstrap' AND name='initial_admin_password'"
        ).fetchone()[0]
    assert encrypted.startswith("v2:")
    assert "initial_admin_password" not in encrypted
    assert master_key.stat().st_mode & 0o777 == 0o600


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

    security_store.initialize_security_store()
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
    security_store.initialize_security_store()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE users SET password_hash='broken' WHERE username='admin'")
        connection.commit()
    status = security_store.authentication_readiness()
    assert status["ready"] is False
    assert status["invalid_password_hashes"] == 1


@pytest.mark.asyncio
async def test_schedule_batches_all_backups_then_prunes_and_compacts_once_per_repository(monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app import service
    from app.database import Base, SessionLocal, engine
    from app.models import Host, Job, Repository

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        repository = Repository(name=f"batch-repo-{suffix}", location=f"/tmp/{suffix}", initialized=True)
        first_host = Host(name=f"batch-host-a-{suffix}", address="127.0.0.1", username="root", host_key="key")
        second_host = Host(name=f"batch-host-b-{suffix}", address="127.0.0.2", username="root", host_key="key")
        db.add_all([repository, first_host, second_host]); db.flush()
        first = Job(name=f"batch-job-a-{suffix}", host_id=first_host.id, repository_id=repository.id,
                    source_paths_json='["/srv/a"]', prune_options_json=json.dumps({"daily": 7}))
        second = Job(name=f"batch-job-b-{suffix}", host_id=second_host.id, repository_id=repository.id,
                     source_paths_json='["/srv/b"]', prune_options_json=json.dumps({"daily": 7}))
        db.add_all([first, second]); db.commit()
        job_ids = [first.id, second.id]
        repository_id = repository.id

    queued: list[tuple[int, str]] = []
    next_run_id = iter(range(500, 510))
    refreshed: list[int] = []

    def queue(job_id_arg, action, restore=None, **_kwargs):
        queued.append((job_id_arg, action))
        return next(next_run_id)

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

    await service._scheduled_backup_group(job_ids, "Nachtlauf", schedule_id=77, schedule_parallel_limit=2)

    assert queued[:2] == [(job_ids[0], "backup"), (job_ids[1], "backup")]
    assert queued[2:4] == [(job_ids[0], "prune"), (job_ids[1], "prune")]
    assert queued[4:] == [(job_ids[0], "compact")]
    assert refreshed == [repository_id]


@pytest.mark.asyncio
async def test_manual_backup_chain_runs_prune_then_compact_and_releases_reservation(monkeypatch):
    from types import SimpleNamespace
    from app import service

    queued: list[tuple[int, str, str | None]] = []
    run_ids = iter([701, 702])
    released: list[str] = []
    refreshed: list[int] = []

    def queue(job_id, action, restore=None, **kwargs):
        queued.append((job_id, action, kwargs.get("chain_token")))
        return next(run_ids)

    statuses = {700: "success", 701: "success", 702: "success"}

    async def wait(run_id):
        return statuses[run_id]

    async def refresh(repository_id):
        refreshed.append(repository_id)
        return {}

    monkeypatch.setattr(service, "queue_job_action", queue)
    monkeypatch.setattr(service, "_wait_for_run", wait)
    monkeypatch.setattr(service, "_release_repository_chain", released.append)
    monkeypatch.setattr(service, "refresh_repository_statistics", refresh)
    monkeypatch.setattr(service, "load_settings", lambda: SimpleNamespace(
        repository_size_after_run=True,
        run_log_max_mib=50,
    ))

    await service._finish_manual_backup_chain(
        9, 700, 11, "manual-token", compact_after=True,
    )

    assert queued == [
        (9, "prune", "manual-token"),
        (9, "compact", "manual-token"),
    ]
    assert released == ["manual-token"]
    assert refreshed == [11]
