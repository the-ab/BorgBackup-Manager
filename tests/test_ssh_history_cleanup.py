from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text

import app.ssh_history_cleanup as cleanup


def _create_history_database(path: Path) -> object:
    target_engine = create_engine(f"sqlite:///{path}")
    with target_engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                command_preview TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                log_output TEXT NOT NULL DEFAULT '',
                warning_summary_json TEXT NOT NULL DEFAULT ''
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE notification_deliveries (
                id INTEGER PRIMARY KEY,
                run_id INTEGER,
                detail TEXT NOT NULL DEFAULT ''
            )
            """
        ))
    return target_engine


def test_legacy_ssh_run_history_is_sanitized_completely(tmp_path, monkeypatch):
    database_path = tmp_path / "manager.db"
    target_engine = _create_history_database(database_path)
    secret = "username=backup,password=TopSecret123!"
    old_preview = (
        "ssh -i [temporärer Controller-Schlüssel] backup@host -- sh -lc "
        f"'mount -t cifs -o {secret} //server/share /mnt/share'"
    )
    with target_engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview,output,error,log_output,warning_summary_json)
            VALUES(1,'ssh-command',:preview,:secret,:secret,:secret,:secret)
            """
        ), {"preview": old_preview, "secret": secret})
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview,output,error,log_output,warning_summary_json)
            VALUES(2,'ssh-command','Gespeicherte SSH-Aktion: Status · Gerät: host','safe output','','','')
            """
        ))
        connection.execute(text(
            "INSERT INTO notification_deliveries(id,run_id,detail) VALUES(1,1,:secret)"
        ), {"secret": secret})

    run_log = tmp_path / "run-1.log"
    run_log.write_text(secret, encoding="utf-8")
    monkeypatch.setattr(cleanup, "run_log_path", lambda run_id: tmp_path / f"run-{run_id}.log")
    monkeypatch.setattr(cleanup, "delete_run_log", lambda run_id: (tmp_path / f"run-{run_id}.log").unlink(missing_ok=True))
    marked: list[bool] = []
    monkeypatch.setattr(cleanup, "mark_manager_vacuum_pending", lambda: marked.append(True))

    assert cleanup.legacy_ssh_run_history_status(target_engine)["rows"] == 1
    assert cleanup.manager_database_legacy_marker_files(target_engine) == [database_path]
    result = cleanup.sanitize_legacy_ssh_run_history(target_engine)
    assert result["rows_sanitized"] == 1
    assert result["notification_details_sanitized"] == 1
    assert result["run_logs_removed"] == 1
    assert marked == [True]
    assert not run_log.exists()

    with target_engine.connect() as connection:
        sanitized = connection.execute(text(
            "SELECT command_preview,output,error,log_output,warning_summary_json FROM runs WHERE id=1"
        )).one()
        assert sanitized[0] == "Gespeicherte SSH-Aktion (historischer Lauf; Befehlsinhalt entfernt)"
        assert list(sanitized[1:]) == ["", "", "", ""]
        safe = connection.execute(text(
            "SELECT command_preview,output FROM runs WHERE id=2"
        )).one()
        assert safe[1] == "safe output"
        delivery = connection.execute(text(
            "SELECT detail FROM notification_deliveries WHERE id=1"
        )).scalar_one()
        assert delivery == "Historische SSH-Aktionsdetails aus Sicherheitsgründen entfernt."

    target_engine.dispose()
    with sqlite3.connect(database_path) as connection:
        connection.execute("VACUUM")
    assert secret.encode("utf-8") not in database_path.read_bytes()
    cleanup.verify_no_legacy_ssh_plaintext_markers(target_engine)



def test_already_sanitized_history_retries_leftover_run_log_removal(tmp_path, monkeypatch):
    database_path = tmp_path / "manager.db"
    target_engine = _create_history_database(database_path)
    with target_engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview,output,error,log_output,warning_summary_json)
            VALUES(7,'ssh-command','Gespeicherte SSH-Aktion (historischer Lauf; Befehlsinhalt entfernt)','','','','')
            """
        ))

    run_log = tmp_path / "run-7.log"
    run_log.write_text("username=backup,password=leftover-secret", encoding="utf-8")
    monkeypatch.setattr(cleanup, "run_log_path", lambda run_id: tmp_path / f"run-{run_id}.log")
    monkeypatch.setattr(cleanup, "delete_run_log", lambda run_id: (tmp_path / f"run-{run_id}.log").unlink(missing_ok=True))
    marked: list[bool] = []
    monkeypatch.setattr(cleanup, "mark_manager_vacuum_pending", lambda: marked.append(True))

    status = cleanup.legacy_ssh_run_history_status(target_engine)
    assert status["rows"] == 0
    assert status["run_logs"] == 1

    result = cleanup.sanitize_legacy_ssh_run_history(target_engine)
    assert result["rows_sanitized"] == 0
    assert result["run_logs_removed"] == 1
    assert marked == []
    assert not run_log.exists()



def test_cleanup_preserves_jobs_schedules_hosts_repositories_and_backup_statistics(tmp_path, monkeypatch):
    database_path = tmp_path / "manager.db"
    target_engine = create_engine(f"sqlite:///{database_path}")
    secret = "username=backup,password=DoNotKeepMe"
    with target_engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, command_preview TEXT NOT NULL DEFAULT '',
                output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                log_output TEXT NOT NULL DEFAULT '', warning_summary_json TEXT NOT NULL DEFAULT '',
                backup_original_size_bytes INTEGER, backup_compressed_size_bytes INTEGER,
                backup_deduplicated_size_bytes INTEGER, backup_file_count INTEGER
            )
            """
        ))
        connection.execute(text("CREATE TABLE hosts (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        connection.execute(text("CREATE TABLE repositories (id INTEGER PRIMARY KEY, name TEXT NOT NULL, size_bytes INTEGER)"))
        connection.execute(text(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, host_id INTEGER, repository_id INTEGER,
                source_size_bytes INTEGER, source_file_count INTEGER, source_stats_checked_at TEXT
            )
            """
        ))
        connection.execute(text(
            "CREATE TABLE backup_schedules (id INTEGER PRIMARY KEY, name TEXT NOT NULL, expressions TEXT NOT NULL)"
        ))
        connection.execute(text("INSERT INTO hosts VALUES(1,'server-a')"))
        connection.execute(text("INSERT INTO repositories VALUES(1,'repo-a',987654321)"))
        connection.execute(text(
            """
            INSERT INTO jobs VALUES(1,'daily',1,1,123456789,4321,'2026-08-01T22:00:00+00:00')
            """
        ))
        connection.execute(text("INSERT INTO backup_schedules VALUES(1,'nightly','0 22 * * *')"))
        connection.execute(text(
            """
            INSERT INTO runs(
                id,action,command_preview,output,error,log_output,warning_summary_json,
                backup_original_size_bytes,backup_compressed_size_bytes,
                backup_deduplicated_size_bytes,backup_file_count
            ) VALUES(10,'backup','borg create','backup output','','','',1000000,800000,100000,250)
            """
        ))
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview,output,error,log_output,warning_summary_json)
            VALUES(11,'ssh-command',:preview,:secret,:secret,:secret,:secret)
            """
        ), {
            "preview": "ssh -i [temporärer Controller-Schlüssel] root@host -- sh -lc '" + secret + "'",
            "secret": secret,
        })

    monkeypatch.setattr(cleanup, "run_log_path", lambda run_id: tmp_path / f"run-{run_id}.log")
    monkeypatch.setattr(cleanup, "delete_run_log", lambda run_id: (tmp_path / f"run-{run_id}.log").unlink(missing_ok=True))
    monkeypatch.setattr(cleanup, "mark_manager_vacuum_pending", lambda: None)

    cleanup.sanitize_legacy_ssh_run_history(target_engine)

    with target_engine.connect() as connection:
        assert connection.execute(text("SELECT id,name FROM hosts")).all() == [(1, "server-a")]
        assert connection.execute(text("SELECT id,name,size_bytes FROM repositories")).all() == [(1, "repo-a", 987654321)]
        assert connection.execute(text(
            "SELECT id,name,host_id,repository_id,source_size_bytes,source_file_count,source_stats_checked_at FROM jobs"
        )).all() == [(1, "daily", 1, 1, 123456789, 4321, "2026-08-01T22:00:00+00:00")]
        assert connection.execute(text("SELECT id,name,expressions FROM backup_schedules")).all() == [(1, "nightly", "0 22 * * *")]
        assert connection.execute(text(
            """
            SELECT command_preview,output,backup_original_size_bytes,backup_compressed_size_bytes,
                   backup_deduplicated_size_bytes,backup_file_count
              FROM runs WHERE id=10
            """
        )).one() == ("borg create", "backup output", 1000000, 800000, 100000, 250)


def test_sensitive_maintenance_backups_are_detected_and_removed(tmp_path):
    unsafe = tmp_path / "manager-before-cleanup-unsafe.sqlite3"
    safe = tmp_path / "manager-before-cleanup-safe.sqlite3"
    unsafe_engine = _create_history_database(unsafe)
    safe_engine = _create_history_database(safe)
    with unsafe_engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview)
            VALUES(1,'ssh-command','ssh -i [temporärer Controller-Schlüssel] root@host -- sh -lc password=secret')
            """
        ))
    with safe_engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview)
            VALUES(1,'ssh-command','Gespeicherte SSH-Aktion: Status · Gerät: host')
            """
        ))
        connection.execute(text(
            """
            INSERT INTO runs(id,action,command_preview)
            VALUES(2,'backup','ssh -i [temporärer Controller-Schlüssel] backup@host -- sh -c safe-backup')
            """
        ))
    unsafe_engine.dispose()
    safe_engine.dispose()

    paths = cleanup.sensitive_maintenance_backup_paths(tmp_path)
    assert paths == [unsafe]
    assert cleanup.purge_sensitive_maintenance_backups(tmp_path) == 1
    assert not unsafe.exists()
    assert safe.exists()


def test_sqlite_security_pragmas_are_enabled_in_runtime_and_rebuild_paths():
    database_source = Path("app/database.py").read_text(encoding="utf-8")
    maintenance_source = Path("app/sqlite_maintenance.py").read_text(encoding="utf-8")
    assert 'cursor.execute("PRAGMA secure_delete=ON")' in database_source
    assert 'connection.execute("PRAGMA secure_delete=ON")' in maintenance_source
