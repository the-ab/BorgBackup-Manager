from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app import backups, manager_cache


def _prepare_backup_state(monkeypatch, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    database = data / "manager.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('saved')")
    settings = data / "settings.json"
    settings.write_text('{"density":"compact"}', encoding="utf-8")
    security = data / "security"
    security.mkdir()
    security_database = security / "security.db"
    with sqlite3.connect(security_database) as connection:
        connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    (security / "master.key").write_text("test-master-key", encoding="utf-8")
    borg_cache = data / "borg-cache"
    borg_security = data / "borg-security"
    backup_dir = data / "backups"
    monkeypatch.setattr(backups, "DATA_DIR", data)
    monkeypatch.setattr(backups, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backups, "SETTINGS_PATH", settings)
    monkeypatch.setattr(backups, "SECURITY_DATABASE_PATH", security_database)
    monkeypatch.setattr(backups, "MANAGER_BORG_CACHE_DIR", borg_cache)
    monkeypatch.setattr(backups, "MANAGER_BORG_SECURITY_DIR", borg_security)
    monkeypatch.setattr(backups, "DATABASE_URL", f"sqlite:///{database}")
    return data, borg_cache, borg_security, backup_dir


def test_cache_backup_can_include_compressed_manager_cache_and_security(monkeypatch, tmp_path: Path):
    data, borg_cache, borg_security, _backup_dir = _prepare_backup_state(monkeypatch, tmp_path)
    repository_id = "a" * 64
    scoped = borg_cache / "repository-1" / repository_id
    scoped.mkdir(parents=True)
    (scoped / "files").write_bytes(b"A" * 100_000)
    (scoped / "lock.roster").write_text("stale", encoding="utf-8")
    (scoped / "lock.exclusive").mkdir()
    (scoped / "lock.exclusive" / "owner").write_text("stale", encoding="utf-8")
    security_dir = borg_security / repository_id
    security_dir.mkdir(parents=True)
    (security_dir / "location").write_text("ssh://borg@example.invalid/./repo", encoding="utf-8")

    backup = backups.create_cache_backup(
        "1.1.0",
        "cache",
        "correct horse battery staple",
        include_manager_borg_cache=True,
        include_client_borg_cache=False,
        compression="maximum",
    )

    header, _aad, _offset = backups._read_encrypted_header(backup)
    assert header["format_version"] == 2
    assert header["cipher"] == "AES-256-GCM-stream"
    assert header["borg_cache_included"] is True
    assert header["borg_security_included"] is True
    assert header["compression"] == "deflate-9"

    with backups.plain_backup_file(backup, "correct horse battery staple") as plain:
        with zipfile.ZipFile(plain) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
    assert f"data/borg-cache/repository-1/{repository_id}/files" in names
    assert f"data/borg-security/{repository_id}/location" in names
    assert not any("lock.exclusive" in name or "lock.roster" in name for name in names)
    assert manifest["borg_cache_included"] is True
    assert manifest["borg_security_included"] is True
    assert manifest["compression"] == "deflate-9"
    assert manifest["borg_cache_files"] == 1

    with pytest.raises(ValueError, match="Cache-Backup"):
        backups.prepare_full_backup_restore(backup, "correct horse battery staple")

    (scoped / "files").write_bytes(b"new-current-cache")
    result = backups.restore_manager_borg_cache_from_backup(backup, "correct horse battery staple")
    assert result["status"] == "restored"
    assert (backups.MANAGER_BORG_CACHE_DIR / "repository-1" / repository_id / "files").read_bytes() == b"A" * 100_000
    assert result["previous_cache"]

    with pytest.raises(ValueError, match="falsch|verändert"):
        backups.restore_manager_borg_cache_from_backup(backup, "definitely wrong passphrase")


def test_manager_backup_without_cache_keeps_cache_out(monkeypatch, tmp_path: Path):
    _data, borg_cache, borg_security, _backup_dir = _prepare_backup_state(monkeypatch, tmp_path)
    (borg_cache / "repository-1").mkdir(parents=True)
    (borg_cache / "repository-1" / "files").write_text("cache", encoding="utf-8")
    (borg_security / ("b" * 64)).mkdir(parents=True)
    (borg_security / ("b" * 64) / "location").write_text("repo", encoding="utf-8")

    backup = backups.create_full_backup(
        "1.1.0", "normal", "correct horse battery staple"
    )
    with backups.plain_backup_file(backup, "correct horse battery staple") as plain:
        with zipfile.ZipFile(plain) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
    assert not any(name.startswith("data/borg-cache/") for name in names)
    assert not any(name.startswith("data/borg-security/") for name in names)
    assert manifest["borg_cache_included"] is False


def test_orphan_cache_cleanup_keeps_active_associations(monkeypatch, tmp_path: Path):
    cache_root = tmp_path / "borg-cache"
    security_root = tmp_path / "borg-security"
    active_borg_id = "c" * 64
    orphan_borg_id = "d" * 64
    active_scoped = cache_root / "repository-1"
    active_scoped.mkdir(parents=True)
    (active_scoped / "keep").write_text("keep", encoding="utf-8")
    orphan_scoped = cache_root / "repository-99"
    orphan_scoped.mkdir(parents=True)
    (orphan_scoped / "remove").write_text("remove", encoding="utf-8")
    legacy_active = cache_root / active_borg_id
    legacy_active.mkdir()
    (legacy_active / "keep").write_text("keep", encoding="utf-8")
    legacy_orphan = cache_root / orphan_borg_id
    legacy_orphan.mkdir()
    (legacy_orphan / "remove").write_text("remove", encoding="utf-8")
    active_security = security_root / active_borg_id
    active_security.mkdir(parents=True)
    (active_security / "location").write_text("ssh://active", encoding="utf-8")
    orphan_security = security_root / orphan_borg_id
    orphan_security.mkdir()
    (orphan_security / "location").write_text("ssh://removed", encoding="utf-8")

    monkeypatch.setattr(manager_cache, "MANAGER_BORG_CACHE_DIR", cache_root)
    monkeypatch.setattr(manager_cache, "MANAGER_BORG_SECURITY_DIR", security_root)
    monkeypatch.setattr(
        manager_cache,
        "_active_context",
        lambda: ({1}, {"ssh://active"}, {active_borg_id}),
    )

    status = manager_cache.manager_borg_cache_status()
    assert status["orphan_count"] == 3
    assert {item["kind"] for item in status["items"] if item.get("selectable")} == {
        "manager_cache_orphan", "legacy_cache_orphan", "manager_security_orphan"
    }
    assert any(item["kind"] == "manager_security_active" for item in status["items"])

    result = manager_cache.cleanup_orphaned_manager_borg_data()
    assert result["removed_count"] == 3
    assert active_scoped.exists()
    assert legacy_active.exists()
    assert active_security.exists()
    assert not orphan_scoped.exists()
    assert not legacy_orphan.exists()
    assert not orphan_security.exists()


def test_manager_and_cache_backups_are_separate_artifacts(monkeypatch, tmp_path: Path):
    _data, borg_cache, _borg_security, _backup_dir = _prepare_backup_state(monkeypatch, tmp_path)
    (borg_cache / "repository-7").mkdir(parents=True)
    (borg_cache / "repository-7" / "files").write_bytes(b"cache-metadata" * 100)

    manager = backups.create_full_backup("1.1.0", "manager", "correct horse battery staple")
    cache = backups.create_cache_backup(
        "1.1.0",
        "cache",
        encrypted=False,
        include_manager_borg_cache=True,
        include_client_borg_cache=False,
    )

    assert manager.name.startswith("borgbackup-manager-backup-v1.1.0-")
    assert manager.suffix == ".bbm"
    assert cache.name.startswith("borgbackup-manager-cache-v1.1.0-")
    assert cache.suffix == ".zip"
    listed = {item["name"]: item for item in backups.list_full_backups()}
    assert listed[manager.name]["backup_type"] == "manager"
    assert listed[cache.name]["backup_type"] == "cache"
    assert listed[manager.name]["manifest"]["borg_cache_included"] is False
    assert listed[cache.name]["manifest"]["borg_cache_included"] is True


def test_cache_backup_encryption_is_optional_but_requires_passphrase_when_enabled(monkeypatch, tmp_path: Path):
    _prepare_backup_state(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="Passphrase"):
        backups.create_cache_backup(
            "1.1.0",
            "encrypted",
            encrypted=True,
            include_manager_borg_cache=True,
            include_client_borg_cache=False,
        )
    plain = backups.create_cache_backup(
        "1.1.0",
        "plain",
        encrypted=False,
        include_manager_borg_cache=True,
        include_client_borg_cache=False,
    )
    assert plain.suffix == ".zip"


def test_manager_security_scan_uses_manifest_timestamp_for_duplicate_candidates(monkeypatch, tmp_path: Path):
    cache_root = tmp_path / "borg-cache"
    security_root = tmp_path / "borg-security"
    cache_root.mkdir()
    security_root.mkdir()
    current_id = "a" * 64
    old_id = "b" * 64
    location = "ssh://borg@example.invalid/./same-repo"
    scoped = cache_root / "repository-1" / current_id
    scoped.mkdir(parents=True)
    for repo_id, stamp in ((current_id, "2026-07-26T12:00:00+00:00"), (old_id, "2026-07-25T12:00:00+00:00")):
        target = security_root / repo_id
        target.mkdir()
        (target / "location").write_text(location, encoding="utf-8")
        (target / "manifest-timestamp").write_text(stamp, encoding="utf-8")
    monkeypatch.setattr(manager_cache, "MANAGER_BORG_CACHE_DIR", cache_root)
    monkeypatch.setattr(manager_cache, "MANAGER_BORG_SECURITY_DIR", security_root)
    monkeypatch.setattr(manager_cache, "_active_context", lambda: ({1}, {location}, {current_id}))
    status = manager_cache.manager_borg_cache_status()
    security = {item["name"]: item for item in status["items"] if item.get("entry_type") == "manager_security"}
    assert security[current_id]["kind"] == "manager_security_active"
    assert security[current_id]["manifest_timestamp"] == "2026-07-26T12:00:00+00:00"
    assert security[old_id]["kind"] == "manager_security_duplicate_old"
    assert security[old_id]["selectable"] is True
    assert security[old_id]["default_selected"] is True


def test_manager_cache_cleanup_can_remove_only_selected_entries(monkeypatch, tmp_path: Path):
    cache_root = tmp_path / "borg-cache"
    security_root = tmp_path / "borg-security"
    cache_root.mkdir()
    security_root.mkdir()
    first = cache_root / "repository-90"
    second = cache_root / "repository-91"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(manager_cache, "MANAGER_BORG_CACHE_DIR", cache_root)
    monkeypatch.setattr(manager_cache, "MANAGER_BORG_SECURITY_DIR", security_root)
    monkeypatch.setattr(manager_cache, "_active_context", lambda: (set(), set(), set()))
    status = manager_cache.manager_borg_cache_status()
    selected = next(item["path"] for item in status["items"] if item.get("name") == "repository-90")
    result = manager_cache.cleanup_orphaned_manager_borg_data([selected])
    assert result["removed_count"] == 1
    assert not first.exists()
    assert second.exists()
