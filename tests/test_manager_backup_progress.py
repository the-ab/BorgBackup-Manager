from pathlib import Path
import zipfile

import pytest

from app import client_cache, manager_backup_progress


def setup_function():
    manager_backup_progress.clear_for_tests()


def test_manager_backup_progress_lifecycle_and_event_history():
    task = manager_backup_progress.begin_task(
        "task-1", label="test", backup_type="cache", include_borg_cache=True, include_client_borg_cache=True,
    )
    assert task["status"] == "queued"
    assert task["backup_type"] == "cache"
    manager_backup_progress.update_task(
        "task-1", status="running", stage="database", message="Datenbank-Snapshot wird erstellt …", percent=5.0,
    )
    manager_backup_progress.update_task(
        "task-1", status="running", stage="encrypt", message="Backup wird mit AES-256-GCM verschlüsselt …",
        percent=91.0, bytes_done=1024, bytes_total=2048,
    )
    current = manager_backup_progress.current_task()
    assert current is not None
    assert current["stage"] == "encrypt"
    assert current["bytes_done"] == 1024
    assert [event["message"] for event in current["events"]][-2:] == [
        "Datenbank-Snapshot wird erstellt …",
        "Backup wird mit AES-256-GCM verschlüsselt …",
    ]
    finished = manager_backup_progress.finish_task("task-1", backup={"name": "backup.bbm", "size_bytes": 1234})
    assert finished["status"] == "finished"
    assert finished["percent"] == 100.0
    assert manager_backup_progress.current_task() is None
    assert manager_backup_progress.get_task("task-1")["backup"]["name"] == "backup.bbm"


def test_manager_backup_progress_rejects_second_active_task():
    manager_backup_progress.begin_task("task-1", label="one", include_borg_cache=False, include_client_borg_cache=False)
    with pytest.raises(ValueError, match="bereits"):
        manager_backup_progress.begin_task("task-2", label="two", include_borg_cache=False, include_client_borg_cache=False)


def test_client_cache_collection_reports_target_and_bytes(monkeypatch, tmp_path: Path):
    host = type("HostRow", (), {"id": 11, "name": "client-11", "enabled": True, "borg_version": "1.2.8"})()
    repository = type("RepositoryRow", (), {"id": 21, "name": "repo-21", "location": "ssh://borg@example.invalid/./repo-21"})()
    monkeypatch.setattr(client_cache, "_target_rows", lambda: [(host, repository)])

    def fake_stream(archive, _host, _repository, arcname, progress=None):
        if progress:
            progress(5)
            progress(12)
        archive.writestr(arcname, b"cache-payload")
        return "present", 12

    monkeypatch.setattr(client_cache, "_stream_one_cache", fake_stream)

    def fake_security_stream(archive, _host, _repository, arcname, progress=None):
        if progress:
            progress(3)
            progress(5)
        archive.writestr(arcname, b"security-payload")
        return "saved", "a" * 64, 5

    monkeypatch.setattr(client_cache, "_stream_one_security", fake_security_stream)
    events = []
    with zipfile.ZipFile(tmp_path / "cache.zip", "w") as archive:
        entries = client_cache.collect_client_borg_caches(archive, events.append)

    assert entries[0]["status"] == "saved"
    assert [event["event"] for event in events] == [
        "target_start", "target_progress", "target_progress", "target_progress",
        "target_progress", "target_progress", "target_done",
    ]
    assert [event.get("component") for event in events] == [
        "cache", "cache", "cache", "security", "security", "security", "complete",
    ]
    assert events[-2]["bytes_done"] == 17
    assert events[-1]["status"] == "saved"
    assert events[-1]["security_status"] == "saved"


def test_cache_backup_progress_can_finish_with_warning():
    manager_backup_progress.begin_task("task-warning", label="test", backup_type="cache")
    result = manager_backup_progress.finish_task(
        "task-warning",
        backup={"name": "cache.bbm", "size_bytes": 55},
        warning="1 Client-Zuordnung konnte nicht gesichert werden.",
    )
    assert result["status"] == "warning"
    assert result["percent"] == 100.0
    assert result["warning"].startswith("1 Client")
    assert any("Warnung:" in event["message"] for event in result["events"])
    assert manager_backup_progress.current_task() is None
