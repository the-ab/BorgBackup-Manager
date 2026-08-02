from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, initialize_manager_database, validate_current_schema
import app.models  # noqa: F401
from app.models import BackupSchedule, Host, Job, Repository, Run


def _file_engine(path: Path):
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})


def test_fresh_database_is_created_with_current_schema():
    target = create_engine("sqlite://")
    result = initialize_manager_database(target)
    inspector = inspect(target)
    assert set(Base.metadata.tables) <= set(inspector.get_table_names())
    assert result["rebuilt"] is False
    validate_current_schema(target)


def test_incomplete_prebaseline_database_is_rejected():
    target = create_engine("sqlite://")
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
    with pytest.raises(RuntimeError, match="älter als die unterstützte Baseline"):
        initialize_manager_database(target)


def test_real_v135_database_with_archive_mounts_is_normalized_and_preserves_current_data(tmp_path: Path):
    database = tmp_path / "manager.db"
    target = _file_engine(database)
    Base.metadata.create_all(target)
    with target.begin() as connection:
        connection.execute(text(
            "INSERT INTO hosts(id,name,address,port,username,enabled,repository_ready,created_at) "
            "VALUES(1,'client-a','192.0.2.10',22,'root',1,1,'2026-08-02T10:00:00+00:00')"
        ))
        connection.execute(text(
            "CREATE TABLE archive_mounts (id INTEGER PRIMARY KEY, repository_id INTEGER, mount_path TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO archive_mounts(id,repository_id,mount_path) VALUES(7,1,'/obsolete/mount')"
        ))

    result = initialize_manager_database(target)

    assert result["rebuilt"] is True
    assert result["backup"]
    inspector = inspect(target)
    assert "archive_mounts" not in inspector.get_table_names()
    with target.connect() as connection:
        row = connection.execute(text("SELECT id,name,address,username FROM hosts WHERE id=1")).one()
        assert tuple(row) == (1, "client-a", "192.0.2.10", "root")
    validate_current_schema(target)



def test_v135_baseline_preserves_jobs_schedules_source_stats_and_backup_sizes(tmp_path: Path):
    database = tmp_path / "manager.db"
    target = _file_engine(database)
    Base.metadata.create_all(target)
    Session = sessionmaker(bind=target, expire_on_commit=False)
    with Session() as db:
        host = Host(name="client", address="192.0.2.20", username="root", repository_ready=True)
        repository = Repository(
            name="repo", location="/repositories/repo", initialized=True,
            size_bytes=9000, original_size_bytes=8000, compressed_size_bytes=5000,
            deduplicated_size_bytes=3000,
        )
        db.add_all([host, repository]); db.flush()
        job = Job(
            name="job", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv/data"]', source_size_bytes=123456,
            source_file_count=789, source_stats_origin="backup",
            source_stats_detail_json='{"quality":"high"}',
        )
        db.add(job); db.flush()
        schedule = BackupSchedule(
            name="nightly", expressions="0 2 * * *", target_mode="jobs",
            target_job_ids_json=f"[{job.id}]", enabled=True,
        )
        run = Run(
            job_id=job.id, repository_id=repository.id, action="backup", status="success",
            backup_original_size_bytes=7000, backup_compressed_size_bytes=4500,
            backup_deduplicated_size_bytes=2500, backup_file_count=700,
            backup_source_size_bytes_snapshot=123456, backup_source_file_count_snapshot=789,
        )
        db.add_all([schedule, run]); db.commit()
        expected = {
            "host_id": host.id, "repository_id": repository.id, "job_id": job.id,
            "schedule_id": schedule.id, "run_id": run.id,
        }
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE archive_mounts (id INTEGER PRIMARY KEY, mount_path TEXT)"))
        connection.execute(text("INSERT INTO archive_mounts(id,mount_path) VALUES(1,'/legacy')"))

    initialize_manager_database(target)

    with target.connect() as connection:
        assert connection.execute(text("SELECT name,address,username FROM hosts WHERE id=:id"), {"id": expected["host_id"]}).one() == ("client", "192.0.2.20", "root")
        assert connection.execute(text("SELECT name,size_bytes,original_size_bytes,compressed_size_bytes,deduplicated_size_bytes FROM repositories WHERE id=:id"), {"id": expected["repository_id"]}).one() == ("repo", 9000, 8000, 5000, 3000)
        assert connection.execute(text("SELECT name,source_size_bytes,source_file_count,source_stats_origin,source_stats_detail_json FROM jobs WHERE id=:id"), {"id": expected["job_id"]}).one() == ("job", 123456, 789, "backup", '{"quality":"high"}')
        assert connection.execute(text("SELECT name,expressions,target_mode,target_job_ids_json,enabled FROM backup_schedules WHERE id=:id"), {"id": expected["schedule_id"]}).one() == ("nightly", "0 2 * * *", "jobs", f"[{expected['job_id']}]", 1)
        assert connection.execute(text("SELECT backup_original_size_bytes,backup_compressed_size_bytes,backup_deduplicated_size_bytes,backup_file_count,backup_source_size_bytes_snapshot,backup_source_file_count_snapshot FROM runs WHERE id=:id"), {"id": expected["run_id"]}).one() == (7000, 4500, 2500, 700, 123456, 789)


def test_real_v135_database_with_unknown_surplus_table_is_normalized(tmp_path: Path):
    database = tmp_path / "manager.db"
    target = _file_engine(database)
    Base.metadata.create_all(target)
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE obsolete_transition_state (id INTEGER PRIMARY KEY, note TEXT)"))
        connection.execute(text("INSERT INTO obsolete_transition_state(id,note) VALUES(1,'legacy')"))

    result = initialize_manager_database(target)

    assert result["rebuilt"] is True
    assert "obsolete_transition_state" not in inspect(target).get_table_names()
    validate_current_schema(target)


def test_plaintext_host_ssh_action_table_with_data_is_rejected(tmp_path: Path):
    database = tmp_path / "manager.db"
    target = _file_engine(database)
    Base.metadata.create_all(target)
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE host_ssh_actions (id INTEGER PRIMARY KEY, command TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO host_ssh_actions(id,command) VALUES(1,'mount -o password=secret')"))
    with pytest.raises(RuntimeError, match="Vertraulicher SSH-Altbestand"):
        initialize_manager_database(target)


def test_file_sqlite_uses_wal_and_busy_timeout():
    from app.database import engine
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        return
    with engine.connect() as connection:
        assert str(connection.exec_driver_sql("PRAGMA journal_mode").scalar()).casefold() == "wal"
        assert int(connection.exec_driver_sql("PRAGMA busy_timeout").scalar()) >= 30000
        assert int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar()) == 1
