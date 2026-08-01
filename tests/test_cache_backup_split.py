from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import backups, manager_backup_progress
from app.schemas import CacheBackupCreateIn


def _write_fake_artifact(path: Path, *, kind: str, host_id: int | None = None, host_name: str | None = None) -> Path:
    manifest = {
        "format": backups.CACHE_BACKUP_FORMAT,
        "format_version": 2,
        "backup_type": "cache",
        "cache_artifact_kind": kind,
        "app_version": "1.2.10",
        "created_at": "2026-08-01T19:00:00+00:00",
        "label": "test",
        "encrypted": False,
        "borg_cache_included": kind == "manager",
        "borg_security_included": kind == "manager",
        "client_borg_cache_included": kind == "client",
        "client_borg_security_included": kind == "client",
        "client_borg_cache_saved_count": 1 if kind == "client" else 0,
        "client_borg_security_saved_count": 1 if kind == "client" else 0,
        "client_borg_cache_warning_count": 0,
        "source_host_id": host_id,
        "source_host_name": host_name,
        "includes": ["borg_cache"] if kind == "manager" else ["client_borg_cache"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("permissions.json", "{}")
    return path


def test_cache_backup_selection_creates_manager_and_only_selected_device_artifacts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backups, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backups, "DATA_DIR", tmp_path)
    hosts = {1: (1, "Alpha Client", True), 2: (2, "Beta Client", True)}
    monkeypatch.setattr(backups, "_client_host_record", lambda host_id: hosts.get(int(host_id)))
    monkeypatch.setattr(backups, "_all_client_cache_host_ids", lambda: [1, 2])
    calls: list[tuple[str, tuple[int, ...]]] = []

    def fake_create(app_version, label, passphrase=None, **kwargs):
        if kwargs["include_manager_borg_cache"]:
            calls.append(("manager", ()))
            return _write_fake_artifact(tmp_path / "backups" / "borgbackup-manager-cache-manager-v1.2.10-20260801-190000-test.zip", kind="manager")
        host_id = int(kwargs["client_host_ids"][0])
        calls.append(("client", (host_id,)))
        name = hosts[host_id][1].replace(" ", "-")
        return _write_fake_artifact(
            tmp_path / "backups" / f"borgbackup-manager-cache-client-{name}-h{host_id}-v1.2.10-20260801-190000-test.zip",
            kind="client", host_id=host_id, host_name=hosts[host_id][1],
        )

    monkeypatch.setattr(backups, "create_cache_backup", fake_create)
    result = backups.create_cache_backup_set(
        "1.2.10", "test", encrypted=False,
        include_manager_borg_cache=True,
        include_client_borg_cache=True,
        client_host_ids=[2],
    )

    assert calls == [("manager", ()), ("client", (2,))]
    assert len(result["paths"]) == 2
    assert any("cache-manager" in path.name for path in result["paths"])
    assert any("Beta-Client-h2" in path.name for path in result["paths"])
    assert all("Alpha" not in path.name for path in result["paths"])


def test_cache_backup_all_scope_expands_to_all_assigned_devices(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backups, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backups, "DATA_DIR", tmp_path)
    hosts = {1: (1, "Alpha", True), 2: (2, "Beta", True)}
    monkeypatch.setattr(backups, "_client_host_record", lambda host_id: hosts.get(int(host_id)))
    monkeypatch.setattr(backups, "_all_client_cache_host_ids", lambda: [1, 2])
    called: list[int] = []

    def fake_create(app_version, label, passphrase=None, **kwargs):
        host_id = int(kwargs["client_host_ids"][0])
        called.append(host_id)
        return _write_fake_artifact(
            tmp_path / "backups" / f"borgbackup-manager-cache-client-{hosts[host_id][1]}-h{host_id}-v1.2.10-20260801-190000-test.zip",
            kind="client", host_id=host_id, host_name=hosts[host_id][1],
        )

    monkeypatch.setattr(backups, "create_cache_backup", fake_create)
    result = backups.create_cache_backup_set(
        "1.2.10", "test", encrypted=False,
        include_manager_borg_cache=False,
        include_client_borg_cache=True,
        client_host_ids=None,
    )
    assert called == [1, 2]
    assert len(result["paths"]) == 2


def test_cache_backup_schema_supports_all_or_selected_devices():
    selected = CacheBackupCreateIn(
        encrypted=False,
        include_manager_borg_cache=False,
        include_client_borg_cache=True,
        client_scope="selected",
        client_host_ids=[3, 2, 3],
    )
    assert selected.client_host_ids == [2, 3]

    all_devices = CacheBackupCreateIn(
        encrypted=False,
        include_manager_borg_cache=False,
        include_client_borg_cache=True,
        client_scope="all",
        client_host_ids=[9],
    )
    assert all_devices.client_host_ids is None

    with pytest.raises(ValidationError, match="at least one device"):
        CacheBackupCreateIn(
            encrypted=False,
            include_manager_borg_cache=False,
            include_client_borg_cache=True,
            client_scope="selected",
            client_host_ids=[],
        )


def test_backup_progress_can_return_multiple_cache_artifacts():
    manager_backup_progress.clear_for_tests()
    task = manager_backup_progress.begin_task("split", label="test", backup_type="cache")
    assert task["backups"] == []
    finished = manager_backup_progress.finish_task(
        "split",
        backup={"name": "manager.zip", "size_bytes": 10},
        backups=[
            {"name": "manager.zip", "size_bytes": 10},
            {"name": "client-alpha.zip", "size_bytes": 20},
        ],
    )
    assert finished["status"] == "finished"
    assert [item["name"] for item in finished["backups"]] == ["manager.zip", "client-alpha.zip"]
