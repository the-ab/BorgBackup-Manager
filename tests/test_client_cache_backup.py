from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import subprocess
import tarfile
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet

import pytest

from app import backups, client_cache, runner
from app.models import Host, Repository


HOST_KEY = "host.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEtesthostkeymaterial"


def _host(host_id: int = 11, *, enabled: bool = True) -> Host:
    return Host(
        id=host_id,
        name=f"client-{host_id}",
        address=f"10.0.0.{host_id}",
        port=22,
        username="backup",
        enabled=enabled,
        host_key=HOST_KEY,
        borg_version="1.2.8",
    )


def _repository(repository_id: int = 21) -> Repository:
    return Repository(
        id=repository_id,
        name=f"repo-{repository_id}",
        location=f"ssh://borg@example.invalid/./repo-{repository_id}",
        extra_env_json="{}",
    )


def _prepare_backup_state(monkeypatch, tmp_path: Path) -> None:
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
    master_key = Fernet.generate_key()
    cipher = Fernet(master_key)
    with sqlite3.connect(security_database) as connection:
        connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
        connection.execute("INSERT INTO users(username) VALUES ('admin')")
        connection.execute("CREATE TABLE secrets(scope TEXT, name TEXT, encrypted_value TEXT)")
        for secret_name in sorted(backups._REQUIRED_SYSTEM_SECRET_NAMES):
            encrypted = "v2:" + cipher.encrypt(f"value-{secret_name}".encode()).decode("ascii")
            connection.execute("INSERT INTO secrets VALUES ('system', ?, ?)", (secret_name, encrypted))
    (security / "master.key").write_bytes(master_key + b"\n")

    monkeypatch.setattr(backups, "DATA_DIR", data)
    monkeypatch.setattr(backups, "BACKUP_DIR", data / "backups")
    monkeypatch.setattr(backups, "SETTINGS_PATH", settings)
    monkeypatch.setattr(backups, "SECURITY_DATABASE_PATH", security_database)
    monkeypatch.setattr(backups, "MANAGER_BORG_CACHE_DIR", data / "borg-cache")
    monkeypatch.setattr(backups, "MANAGER_BORG_SECURITY_DIR", data / "borg-security")
    monkeypatch.setattr(backups, "DATABASE_URL", f"sqlite:///{database}")


def test_client_cache_commands_use_private_repository_cache_and_harden_restore(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()

    export = runner.client_borg_cache_export_command(host, 21)
    export_script = next(argument for argument in export.argv if "BBM_CLIENT_CACHE_V1" in argument)
    assert 'cache_name="repository-$repository_id"' in export_script
    assert 'borgbackup-manager' in export_script
    assert "lock.exclusive" in export_script
    assert "lock.roster" in export_script
    assert "symbolischen Link" in export_script
    assert "StrictHostKeyChecking=yes" in " ".join(export.argv)

    restore = runner.client_borg_cache_restore_command(host, 21)
    restore_script = next(argument for argument in restore.argv if "BBM_CLIENT_CACHE_RESTORED" in argument)
    assert 'pre-bbm-restore-$stamp' in restore_script
    assert "--no-same-owner --no-same-permissions" in restore_script
    assert "unerwartete zusätzliche Pfade" in restore_script
    assert "symbolische Links" in restore_script
    assert "lock.exclusive" in restore_script
    assert "lock.roster" in restore_script


def test_client_cache_remote_shell_round_trip_preserves_existing_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache = home / ".cache" / "borgbackup-manager" / "repository-21"
    cache.mkdir(parents=True)
    (cache / "files").write_bytes(b"saved-cache-data")
    (cache / "lock.roster").write_text("volatile", encoding="utf-8")
    (cache / "lock.exclusive").mkdir()
    (cache / "lock.exclusive" / "owner").write_text("volatile", encoding="utf-8")
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}

    export_remote = runner.client_borg_cache_export_command(host, 21).argv[-1]
    exported = subprocess.run(["sh", "-c", export_remote], env=environment, capture_output=True, check=True)
    protocol, status, payload = exported.stdout.split(b"\n", 2)
    assert protocol == b"BBM_CLIENT_CACHE_V1"
    assert status == b"PRESENT"
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        names = archive.getnames()
    assert "repository-21/files" in names
    assert not any("lock.exclusive" in name or "lock.roster" in name for name in names)

    (cache / "files").write_bytes(b"newer-local-cache-data")
    restore_remote = runner.client_borg_cache_restore_command(host, 21).argv[-1]
    restored = subprocess.run(["sh", "-c", restore_remote], env=environment, input=payload, capture_output=True)
    assert restored.returncode == 0, restored.stderr.decode("utf-8", errors="replace")
    assert b"BBM_CLIENT_CACHE_RESTORED" in restored.stdout
    assert (cache / "files").read_bytes() == b"saved-cache-data"
    previous = list((home / ".cache" / "borgbackup-manager").glob("repository-21.pre-bbm-restore-*"))
    assert len(previous) == 1
    assert (previous[0] / "files").read_bytes() == b"newer-local-cache-data"


@pytest.mark.parametrize("repository_id", [0, -1, True])
def test_client_cache_commands_reject_invalid_repository_ids(monkeypatch, repository_id):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    with pytest.raises(ValueError, match="Repository-ID"):
        runner.client_borg_cache_export_command(_host(), repository_id)
    with pytest.raises(ValueError, match="Repository-ID"):
        runner.client_borg_cache_restore_command(_host(), repository_id)


def test_collect_client_caches_records_disabled_devices_without_contact(monkeypatch, tmp_path: Path):
    enabled = _host(11, enabled=True)
    disabled = _host(12, enabled=False)
    repo_a = _repository(21)
    repo_b = _repository(22)
    monkeypatch.setattr(client_cache, "_target_rows", lambda: [(enabled, repo_a), (disabled, repo_b)])
    contacted: list[tuple[int, int]] = []

    def fake_stream(archive, host, repository, arcname):
        contacted.append((host.id, repository.id))
        archive.writestr(arcname, b"client-cache-tar")
        return "present", len(b"client-cache-tar")

    monkeypatch.setattr(client_cache, "_stream_one_cache", fake_stream)
    monkeypatch.setattr(client_cache, "_stream_one_security", lambda *_args, **_kwargs: ("missing", None, 0))
    destination = tmp_path / "client-cache.zip"
    with zipfile.ZipFile(destination, "w") as archive:
        entries = client_cache.collect_client_borg_caches(archive)

    assert contacted == [(11, 21)]
    assert entries[0]["status"] == "saved"
    assert entries[0]["archive_path"] == "data/client-borg-cache/client-11-h11/repo-21-r21.tar"
    assert entries[1]["status"] == "skipped_disabled"
    assert client_cache.client_cache_summary(entries) == {
        "target_count": 2,
        "saved_count": 1,
        "missing_count": 0,
        "skipped_count": 1,
        "warning_count": 0,
        "tar_bytes": len(b"client-cache-tar"),
        "security_saved_count": 0,
        "security_missing_count": 1,
        "security_unresolved_count": 0,
        "security_tar_bytes": 0,
    }


def test_collect_client_caches_warns_and_continues_when_enabled_device_fails(monkeypatch, tmp_path: Path):
    unavailable = _host(11)
    available = _host(12)
    repo_a = _repository(21)
    repo_b = _repository(22)
    monkeypatch.setattr(client_cache, "_target_rows", lambda: [(unavailable, repo_a), (available, repo_b)])

    def fake_stream(archive, host, repository, arcname, progress=None):
        if host.id == 11:
            raise ValueError("ssh unavailable")
        archive.writestr(arcname, b"saved")
        return "present", 5

    monkeypatch.setattr(client_cache, "_stream_one_cache", fake_stream)
    monkeypatch.setattr(client_cache, "_stream_one_security", lambda *_args, **_kwargs: ("missing", None, 0))
    events = []
    with zipfile.ZipFile(tmp_path / "warning.zip", "w") as archive:
        entries = client_cache.collect_client_borg_caches(archive, events.append)

    assert entries[0]["status"] == "warning"
    assert entries[0]["security_status"] == "warning"
    assert "ssh unavailable" in entries[0]["reason"]
    assert entries[1]["status"] == "saved"
    assert client_cache.client_cache_summary(entries)["warning_count"] == 1
    assert any(event.get("status") == "warning" for event in events)


def test_cache_backup_contains_inventory_and_selectively_restores_client_cache(monkeypatch, tmp_path: Path):
    _prepare_backup_state(monkeypatch, tmp_path)
    cache_payload = b"repository-21/cache-data\n"
    security_payload = b"security-state-tar\n"
    borg_repository_id = "a" * 64

    def fake_collect(archive, progress=None, *, host_ids=None):
        assert host_ids == [11]
        arcname = "data/client-borg-cache/client-11-h11/repo-21-r21.tar"
        security_arcname = "data/client-borg-security/client-11-h11/repo-21-r21.tar"
        archive.writestr(arcname, cache_payload)
        archive.writestr(security_arcname, security_payload)
        return [{
            "host_id": 11,
            "host_name": "client-11",
            "repository_id": 21,
            "repository_name": "repo-21",
            "borg_version": "1.2.8",
            "cache_path": "$HOME/.cache/borgbackup-manager/repository-21",
            "collected_at": "2026-07-26T18:00:00+00:00",
            "status": "saved",
            "archive_path": arcname,
            "tar_bytes": len(cache_payload),
            "security_status": "saved",
            "borg_repository_id": borg_repository_id,
            "security_path": f"$HOME/.config/borg/security/{borg_repository_id}",
            "security_archive_path": security_arcname,
            "security_tar_bytes": len(security_payload),
        }]

    monkeypatch.setattr(client_cache, "collect_client_borg_caches", fake_collect)
    monkeypatch.setattr(backups, "_client_host_record", lambda host_id: (11, "client-11", True))
    backup = backups.create_cache_backup(
        "1.3.5",
        "client-cache",
        "correct horse battery staple",
        include_manager_borg_cache=False,
        include_client_borg_cache=True,
        client_host_ids=[11],
        compression="standard",
    )

    header, _aad, _offset = backups._read_encrypted_header(backup)
    assert header["backup_type"] == "cache"
    assert header["client_borg_cache_included"] is True
    assert header["client_borg_cache_target_count"] == 1
    assert header["client_borg_cache_saved_count"] == 1
    assert header["client_borg_cache_warning_count"] == 0
    assert header["client_borg_security_included"] is True
    assert header["client_borg_security_saved_count"] == 1

    inventory = backups.client_borg_cache_inventory(backup, "correct horse battery staple")
    assert inventory["included"] is True
    assert inventory["saved_count"] == 1
    assert inventory["security_included"] is True
    assert inventory["security_saved_count"] == 1
    assert inventory["entries"][0]["host_id"] == 11
    assert inventory["entries"][0]["repository_id"] == 21

    with pytest.raises(ValueError, match="Cache-Backup"):
        backups.prepare_full_backup_restore(backup, "correct horse battery staple")

    captured: dict[str, bytes | int | str] = {}

    def fake_restore(host, repository_id, source):
        captured["host_id"] = host.id
        captured["repository_id"] = repository_id
        captured["payload"] = source.read()
        return {"status": "restored", "previous_cache": "/home/backup/.cache/borgbackup-manager/repository-21.pre-bbm-restore-test"}

    def fake_security_restore(host, repository_id, source):
        captured["security_host_id"] = host.id
        captured["borg_repository_id"] = repository_id
        captured["security_payload"] = source.read()
        return {"status": "restored", "borg_repository_id": repository_id}

    monkeypatch.setattr(client_cache, "restore_client_borg_cache_stream", fake_restore)
    monkeypatch.setattr(client_cache, "restore_client_borg_security_stream", fake_security_restore)
    result = backups.restore_client_borg_cache_from_backup(
        backup,
        "correct horse battery staple",
        _host(12),
        21,
        source_host_id=11,
        source_repository_id=21,
    )
    assert captured == {
        "host_id": 12, "repository_id": 21, "payload": cache_payload,
        "security_host_id": 12, "borg_repository_id": borg_repository_id,
        "security_payload": security_payload,
    }
    assert result["status"] == "restored"
    assert result["security_status"] == "saved"
    assert result["security_restore"]["status"] == "restored"
    assert result["source_host_name"] == "client-11"
    assert result["target_host_name"] == "client-12"
    assert result["repository_name"] == "repo-21"

    with pytest.raises(ValueError, match="Quell-Client-Cache"):
        backups.restore_client_borg_cache_from_backup(
            backup,
            "correct horse battery staple",
            _host(99),
            21,
            source_host_id=99,
            source_repository_id=21,
        )


def test_client_cache_manifest_rejects_forged_archive_mapping():
    manifest = {
        "client_borg_cache_included": True,
        "client_borg_caches": [{
            "host_id": 11,
            "repository_id": 21,
            "status": "saved",
            "archive_path": "data/client-borg-cache/host-99/repository-21.tar",
        }],
    }
    with pytest.raises(ValueError, match="Archivpfad"):
        backups._client_cache_entries_from_manifest(manifest)


def test_client_cache_scan_command_lists_cache_and_restore_safety_copy(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    home = tmp_path / "home"
    base = home / ".cache" / "borgbackup-manager"
    active = base / "repository-21"
    rollback = base / "repository-21.pre-bbm-restore-20260726-101112"
    active.mkdir(parents=True)
    rollback.mkdir()
    (active / "files").write_bytes(b"a" * 1024)
    (rollback / "files").write_bytes(b"b" * 2048)
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}

    remote = runner.client_borg_cache_scan_command(_host()).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    parsed = client_cache._parse_scan_output(result.stdout, {21})

    assert any(item["name"] == "repository-21" and item["kind"] == "active" for item in parsed)
    safety = next(item for item in parsed if item["name"].startswith("repository-21.pre-bbm-restore-"))
    assert safety["kind"] == "rollback"
    assert safety["repository_id"] == 21
    assert safety["size_bytes"] > 0


def test_parse_client_cache_scan_marks_unassigned_repository_cache_orphan():
    output = "\n".join([
        "BBM_CLIENT_CACHE_SCAN_V1",
        "BASE\tPRESENT",
        "ENTRY\trepository-21\t12",
        "ENTRY\trepository-22\t34",
        "ENTRY\trepository-22.pre-bbm-restore-20260726-101112\t56",
    ])
    entries = client_cache._parse_scan_output(output, {21})
    assert next(item for item in entries if item["name"] == "repository-21")["kind"] == "active"
    assert next(item for item in entries if item["name"] == "repository-22")["kind"] == "orphan"
    assert next(item for item in entries if ".pre-bbm-restore-" in item["name"])["kind"] == "rollback"


def test_client_cache_cleanup_command_removes_only_requested_safe_directories(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    home = tmp_path / "home"
    base = home / ".cache" / "borgbackup-manager"
    active = base / "repository-21"
    orphan = base / "repository-22"
    rollback = base / "repository-21.pre-bbm-restore-20260726-101112"
    active.mkdir(parents=True)
    orphan.mkdir()
    rollback.mkdir()
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}

    remote = runner.client_borg_cache_cleanup_command(_host(), [orphan.name, rollback.name]).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)

    assert "REMOVED\trepository-22" in result.stdout
    assert f"REMOVED\t{rollback.name}" in result.stdout
    assert active.is_dir()
    assert not orphan.exists()
    assert not rollback.exists()


def test_cleanup_orphan_client_cache_rechecks_assignment_before_delete(monkeypatch):
    host = _host()
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, {22})])
    contacted = []
    monkeypatch.setattr(client_cache, "_run_text_command", lambda command: contacted.append(command) or "")
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0, "rollback_count": 0})

    result = client_cache.cleanup_client_borg_caches(
        "orphan", [{"host_id": host.id, "name": "repository-22"}]
    )

    assert result["removed_count"] == 0
    assert result["skipped"]
    assert "inzwischen wieder" in result["skipped"][0]["reason"]
    assert contacted == []


def test_cleanup_restore_safety_copy_uses_separate_kind(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, {21})])
    monkeypatch.setattr(
        client_cache,
        "_run_text_command",
        lambda command: "BBM_CLIENT_CACHE_CLEANUP_V1\nREMOVED\trepository-21.pre-bbm-restore-20260726-101112\n",
    )
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0, "rollback_count": 0})

    result = client_cache.cleanup_client_borg_caches(
        "rollback",
        [{"host_id": host.id, "name": "repository-21.pre-bbm-restore-20260726-101112"}],
    )

    assert result["removed_count"] == 1
    assert result["removed"][0]["name"].endswith("20260726-101112")


def test_client_security_remote_round_trip_and_preserves_existing_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    repository = _repository(21)
    borg_repository_id = "a" * 64
    home = tmp_path / "home"
    cache = home / ".cache" / "borgbackup-manager" / "repository-21"
    cache.mkdir(parents=True)
    (cache / "config").write_text(
        f"[cache]\nversion = 1\nrepository = {borg_repository_id}\nmanifest = 00\n",
        encoding="utf-8",
    )
    security = home / ".config" / "borg" / "security" / borg_repository_id
    security.mkdir(parents=True)
    (security / "location").write_text(repository.location, encoding="utf-8")
    (security / "key-type").write_text("repokey", encoding="utf-8")
    (security / "manifest-timestamp").write_text("2026-07-26T10:11:12.000000", encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }

    export_remote = runner.client_borg_security_export_command(host, 21, repository.location).argv[-1]
    exported = subprocess.run(["sh", "-c", export_remote], env=environment, capture_output=True, check=True)
    protocol, status, reported_id, payload = exported.stdout.split(b"\n", 3)
    assert protocol == b"BBM_CLIENT_SECURITY_V1"
    assert status == b"PRESENT"
    assert reported_id.decode() == borg_repository_id
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        assert f"{borg_repository_id}/location" in archive.getnames()
        assert f"{borg_repository_id}/key-type" in archive.getnames()
        assert f"{borg_repository_id}/manifest-timestamp" in archive.getnames()

    # Missing local state is restored.
    import shutil
    shutil.rmtree(security)
    restore_remote = runner.client_borg_security_restore_command(host, borg_repository_id).argv[-1]
    restored = subprocess.run(["sh", "-c", restore_remote], env=environment, input=payload, capture_output=True)
    assert restored.returncode == 0, restored.stderr.decode("utf-8", errors="replace")
    assert b"BBM_CLIENT_SECURITY_RESTORED" in restored.stdout
    assert (security / "manifest-timestamp").read_text(encoding="utf-8") == "2026-07-26T10:11:12.000000"

    # Existing state is deliberately kept, even if the backup contains an older value.
    (security / "manifest-timestamp").write_text("NEWER-LOCAL-STATE", encoding="utf-8")
    kept = subprocess.run(["sh", "-c", restore_remote], env=environment, input=payload, capture_output=True)
    assert kept.returncode == 0, kept.stderr.decode("utf-8", errors="replace")
    assert b"BBM_CLIENT_SECURITY_KEPT_EXISTING" in kept.stdout
    assert (security / "manifest-timestamp").read_text(encoding="utf-8") == "NEWER-LOCAL-STATE"


def test_client_scan_classifies_security_active_orphan_and_unknown(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache_base = home / ".cache" / "borgbackup-manager"
    security_base = home / ".config" / "borg" / "security"
    active_id = "a" * 64
    orphan_id = "b" * 64
    unknown_id = "c" * 64
    active_location = "ssh://borg@example.invalid/./repo-21"
    orphan_location = "ssh://borg@example.invalid/./repo-22"

    for repository_id, borg_id in ((21, active_id), (22, orphan_id)):
        cache = cache_base / f"repository-{repository_id}"
        cache.mkdir(parents=True)
        (cache / "config").write_text(f"[cache]\nrepository = {borg_id}\n", encoding="utf-8")
    for borg_id, location in (
        (active_id, active_location),
        (orphan_id, orphan_location),
        (unknown_id, "ssh://manual@example.invalid/./unmanaged"),
    ):
        target = security_base / borg_id
        target.mkdir(parents=True)
        (target / "location").write_text(location, encoding="utf-8")
        (target / "key-type").write_text("repokey", encoding="utf-8")
        (target / "manifest-timestamp").write_text("timestamp", encoding="utf-8")

    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    remote = runner.client_borg_cache_scan_command(host).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    entries = client_cache._parse_scan_output(
        result.stdout,
        {21},
        assigned_locations={active_location},
        known_locations={active_location, orphan_location},
    )

    security_entries = {item["name"]: item for item in entries if item.get("entry_type") == "security"}
    assert security_entries[active_id]["kind"] == "security_active"
    assert security_entries[orphan_id]["kind"] == "security_orphan"
    assert security_entries[unknown_id]["kind"] == "security_unknown"


def test_security_cleanup_command_removes_only_explicit_repository_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    security_base = home / ".config" / "borg" / "security"
    remove_id = "b" * 64
    keep_id = "c" * 64
    (security_base / remove_id).mkdir(parents=True)
    (security_base / keep_id).mkdir(parents=True)
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }

    remote = runner.client_borg_security_cleanup_command(host, [remove_id]).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert f"REMOVED\t{remove_id}" in result.stdout
    assert not (security_base / remove_id).exists()
    assert (security_base / keep_id).is_dir()


def test_client_scan_v4_includes_normal_borg_cache_manifest_timestamp_and_duplicate_detection(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    bbm_cache = home / ".cache" / "borgbackup-manager" / "repository-21"
    bbm_cache.mkdir(parents=True)
    active_id = "a" * 64
    older_id = "b" * 64
    unknown_id = "c" * 64
    (bbm_cache / "config").write_text(f"[cache]\nrepository = {active_id}\n", encoding="utf-8")
    normal_cache = home / ".cache" / "borg"
    for repo_id in (active_id, older_id, unknown_id):
        (normal_cache / repo_id).mkdir(parents=True)
        (normal_cache / repo_id / "files").write_text("cache", encoding="utf-8")
    security_base = home / ".config" / "borg" / "security"
    location = "ssh://borg@example.invalid/./repo-21"
    for repo_id, stamp in ((active_id, "2026-07-26T10:00:00+00:00"), (older_id, "2026-07-25T10:00:00+00:00")):
        target = security_base / repo_id
        target.mkdir(parents=True)
        (target / "location").write_text(location, encoding="utf-8")
        (target / "manifest-timestamp").write_text(stamp, encoding="utf-8")
    unknown_security = security_base / unknown_id
    unknown_security.mkdir(parents=True)
    (unknown_security / "location").write_text("ssh://manual.invalid/./repo", encoding="utf-8")
    (unknown_security / "manifest-timestamp").write_text("2026-07-24T10:00:00+00:00", encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    remote = runner.client_borg_cache_scan_command(host).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert result.stdout.startswith("BBM_CLIENT_CACHE_SCAN_V5\n")
    entries = client_cache._parse_scan_output(
        result.stdout,
        {21},
        assigned_locations={location},
        known_locations={location},
    )
    by_key = {(item["entry_type"], item["name"]): item for item in entries}
    assert by_key[("user_cache", active_id)]["kind"] == "user_cache_active"
    assert by_key[("user_cache", older_id)]["kind"] == "user_cache_orphan"
    assert by_key[("user_cache", unknown_id)]["kind"] == "user_cache_unknown"
    assert by_key[("user_cache", unknown_id)]["selectable"] is True
    assert by_key[("security", active_id)]["kind"] == "security_active"
    assert by_key[("security", active_id)]["manifest_timestamp"] == "2026-07-26T10:00:00+00:00"
    assert by_key[("security", older_id)]["kind"] == "security_duplicate_old"
    assert by_key[("security", older_id)]["default_selected"] is True
    assert by_key[("security", unknown_id)]["kind"] == "security_unknown"
    assert by_key[("security", unknown_id)]["selectable"] is True
    assert by_key[("security", unknown_id)]["default_selected"] is False


def test_normal_borg_cache_cleanup_removes_only_explicit_repository_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache_base = home / ".cache" / "borg"
    remove_id = "d" * 64
    keep_id = "e" * 64
    (cache_base / remove_id).mkdir(parents=True)
    (cache_base / keep_id).mkdir(parents=True)
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}
    remote = runner.client_borg_user_cache_cleanup_command(host, [remove_id]).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert f"REMOVED\t{remove_id}" in result.stdout
    assert not (cache_base / remove_id).exists()
    assert (cache_base / keep_id).is_dir()



def test_normal_borg_cache_scan_ignores_cachedir_tag_and_finds_hidden_legacy_entries(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache_base = home / ".cache" / "borg"
    cache_base.mkdir(parents=True)
    (cache_base / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n", encoding="utf-8")
    hidden = cache_base / ".legacy-borg-cache"
    hidden.mkdir()
    (hidden / "files").write_bytes(b"x" * (128 * 1024))
    loose_file = cache_base / "old-cache.tmp"
    loose_file.write_bytes(b"y" * (64 * 1024))
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}

    remote = runner.client_borg_cache_scan_command(host).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert result.stdout.startswith("BBM_CLIENT_CACHE_SCAN_V5\n")
    assert "USER_CACHE_META5\tCACHEDIR.TAG" in result.stdout
    entries = client_cache._parse_scan_output(result.stdout, set())
    by_name = {item["name"]: item for item in entries if item.get("entry_type") == "user_cache"}
    assert "CACHEDIR.TAG" not in by_name
    assert "cachedir.tag" not in by_name
    assert by_name[".legacy-borg-cache"]["kind"] == "user_cache_misc"
    assert by_name[".legacy-borg-cache"]["selectable"] is True
    assert by_name[".legacy-borg-cache"]["default_selected"] is False
    assert by_name[".legacy-borg-cache"]["size_bytes"] >= 128 * 1024
    assert by_name[".legacy-borg-cache"]["path"] == str(hidden)
    assert by_name["old-cache.tmp"]["kind"] == "user_cache_misc"
    assert by_name["old-cache.tmp"]["path"] == str(loose_file)
    assert by_name["old-cache.tmp"]["selectable"] is True


def test_normal_borg_cache_cleanup_can_remove_explicit_legacy_entry_but_never_cachedir_tag(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache_base = home / ".cache" / "borg"
    cache_base.mkdir(parents=True)
    (cache_base / "CACHEDIR.TAG").write_text("marker", encoding="utf-8")
    legacy = cache_base / ".legacy-cache"
    legacy.mkdir()
    (legacy / "files").write_bytes(b"legacy")
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}

    remote = runner.client_borg_user_cache_cleanup_command(host, [".legacy-cache"]).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert "REMOVED\t.legacy-cache" in result.stdout
    assert not legacy.exists()
    assert (cache_base / "CACHEDIR.TAG").is_file()
    with pytest.raises(ValueError, match="Borg-Cache-Name"):
        runner.client_borg_user_cache_cleanup_command(host, ["CACHEDIR.TAG"])

def test_legacy_borg_cache_cleanup_accepts_exact_scanned_absolute_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    cache_base = home / ".cache" / "borg"
    legacy = cache_base / ("f" * 64)
    legacy.mkdir(parents=True)
    (legacy / "files").write_bytes(b"legacy")
    environment = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache")}
    remote = runner.client_borg_user_cache_cleanup_command(host, [str(legacy)]).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    assert f"REMOVED\t{legacy.name}" in result.stdout
    assert not legacy.exists()


def test_scan_client_cache_can_limit_check_to_selected_devices(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host_a = _host(11)
    host_b = _host(12)
    seen = []

    def assignments(host_ids=None):
        assert set(host_ids or []) == {12}
        return [(host_b, {21})]

    monkeypatch.setattr(client_cache, "_host_cache_assignments", assignments)
    monkeypatch.setattr(client_cache, "_repository_locations", lambda: {21: "ssh://borg@example.invalid/./repo-21"})
    monkeypatch.setattr(
        client_cache,
        "_run_text_command",
        lambda command: seen.append(command) or "BBM_CLIENT_CACHE_SCAN_V3\nBASE\tMISSING\nUSER_CACHE_BASE\tMISSING\nSECURITY_BASE\tMISSING\n",
    )
    result = client_cache.scan_client_borg_caches([12])
    assert result["selection_mode"] == "selected"
    assert result["requested_host_ids"] == [12]
    assert [device["host_id"] for device in result["devices"]] == [12]
    assert len(seen) == 1
    assert host_a.id not in result["requested_host_ids"]


def test_unknown_security_cleanup_is_allowed_only_after_fresh_unknown_classification(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    unknown_id = "f" * 64
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, set())])
    monkeypatch.setattr(client_cache, "_repository_locations", lambda: {})
    responses = iter([
        f"BBM_CLIENT_CACHE_SCAN_V3\nBASE\tMISSING\nUSER_CACHE_BASE\tMISSING\nSECURITY_BASE\tPRESENT\nSECURITY\t{unknown_id}\t1\tDIR\tLQ==\tLQ==\n",
        f"BBM_CLIENT_SECURITY_CLEANUP_V1\nREMOVED\t{unknown_id}\n",
    ])
    monkeypatch.setattr(client_cache, "_run_text_command", lambda command: next(responses))
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0})
    result = client_cache.cleanup_client_borg_caches("security", [{"host_id": host.id, "name": unknown_id}])
    assert result["removed_count"] == 1


def test_cleanup_client_borg_cache_accepts_selected_misc_normal_cache_after_fresh_scan(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    misc_name = ".legacy-cache"
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, set())])
    monkeypatch.setattr(client_cache, "_repository_locations", lambda: {})
    responses = iter([
        f"BBM_CLIENT_CACHE_SCAN_V4\nBASE\tMISSING\nUSER_CACHE_BASE\tPRESENT\nUSER_CACHE_META\tCACHEDIR.TAG\t4\tCACHEDIR_TAG\nUSER_CACHE\t{misc_name}\t81920\tDIR\nSECURITY_BASE\tMISSING\n",
        f"BBM_CLIENT_USER_CACHE_CLEANUP_V2\nREMOVED\t{misc_name}\n",
    ])
    monkeypatch.setattr(client_cache, "_run_text_command", lambda command: next(responses))
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0})
    result = client_cache.cleanup_client_borg_caches("user_cache", [{"host_id": host.id, "name": misc_name}])
    assert result["removed_count"] == 1


def test_assigned_legacy_borg_cache_is_not_treated_as_bbm_active(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    home = tmp_path / "home"
    borg_id = "a" * 64
    bbm_cache = home / ".cache" / "borgbackup-manager" / "repository-21"
    bbm_cache.mkdir(parents=True)
    (bbm_cache / "config").write_text(f"[cache]\nrepository = {borg_id}\n", encoding="utf-8")
    legacy = home / ".cache" / "borg" / borg_id
    legacy.mkdir(parents=True)
    (legacy / "files").write_bytes(b"legacy-cache")
    security = home / ".config" / "borg" / "security" / borg_id
    security.mkdir(parents=True)
    location = "ssh://borg@example.invalid/./repo-21"
    (security / "location").write_text(location, encoding="utf-8")
    (security / "manifest-timestamp").write_text("2026-07-26T10:00:00+00:00", encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    remote = runner.client_borg_cache_scan_command(host).argv[-1]
    result = subprocess.run(["sh", "-c", remote], env=environment, capture_output=True, check=True, text=True)
    entries = client_cache._parse_scan_output(
        result.stdout,
        {21},
        assigned_locations={location},
        known_locations={location},
    )
    bbm_entry = next(item for item in entries if item["entry_type"] == "cache" and item["name"] == "repository-21")
    legacy_entry = next(item for item in entries if item["entry_type"] == "user_cache" and item["name"] == borg_id)
    assert bbm_entry["kind"] == "active"
    assert bbm_entry["selectable"] is True
    assert bbm_entry["default_selected"] is False
    assert legacy_entry["kind"] == "user_cache_active"
    assert legacy_entry["selectable"] is True
    assert legacy_entry["default_selected"] is False
    assert "wird vom BBM jedoch nicht verwendet" in legacy_entry["reason"]


def test_assigned_legacy_borg_cache_can_be_explicitly_deleted(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    borg_id = "a" * 64
    location = "ssh://borg@example.invalid/./repo-21"
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, {21})])
    monkeypatch.setattr(client_cache, "_repository_locations", lambda: {21: location})
    scan = "\n".join([
        "BBM_CLIENT_CACHE_SCAN_V3",
        "BASE\tPRESENT",
        f"CACHE_REPO\trepository-21\t{borg_id}",
        "ENTRY\trepository-21\t100",
        "USER_CACHE_BASE\tPRESENT",
        f"USER_CACHE\t{borg_id}\t80\tDIR",
        "SECURITY_BASE\tPRESENT",
        f"SECURITY\t{borg_id}\t16\tDIR\t" + base64.b64encode(location.encode()).decode() + "\tMjAyNi0wNy0yNlQxMDowMDowMCswMDowMA==",
    ]) + "\n"
    responses = iter([
        scan,
        f"BBM_CLIENT_USER_CACHE_CLEANUP_V3\nREMOVED\t{borg_id}\n",
    ])
    monkeypatch.setattr(client_cache, "_run_text_command", lambda command: next(responses))
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0})
    result = client_cache.cleanup_client_borg_caches("user_cache", [{"host_id": host.id, "name": borg_id}])
    assert result["removed_count"] == 1


def test_active_bbm_client_cache_reset_requires_idle_and_fresh_active_assignment(monkeypatch):
    monkeypatch.setattr(
        runner,
        "get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = _host()
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, {21})])
    monkeypatch.setattr(client_cache, "_repository_locations", lambda: {21: "ssh://borg@example.invalid/./repo-21"})

    class DummyDB:
        def scalar(self, _query):
            return None
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(client_cache, "SessionLocal", lambda: DummyDB())
    from app import manager_backup_progress
    monkeypatch.setattr(manager_backup_progress, "current_task", lambda include_last=False: None)
    responses = iter([
        "BBM_CLIENT_CACHE_SCAN_V3\nBASE\tPRESENT\nENTRY\trepository-21\t100\nUSER_CACHE_BASE\tMISSING\nSECURITY_BASE\tMISSING\n",
        "BBM_CLIENT_CACHE_CLEANUP_V1\nREMOVED\trepository-21\n",
    ])
    monkeypatch.setattr(client_cache, "_run_text_command", lambda command: next(responses))
    monkeypatch.setattr(client_cache, "scan_client_borg_caches", lambda *args, **kwargs: {"devices": [], "orphan_count": 0})
    result = client_cache.cleanup_client_borg_caches("reset", [{"host_id": host.id, "name": "repository-21"}])
    assert result["removed_count"] == 1


def test_active_bbm_client_cache_reset_is_blocked_while_run_exists(monkeypatch):
    host = _host()
    monkeypatch.setattr(client_cache, "_host_cache_assignments", lambda *args, **kwargs: [(host, {21})])

    class DummyDB:
        def scalar(self, _query):
            return 123
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(client_cache, "SessionLocal", lambda: DummyDB())
    with pytest.raises(ValueError, match="laufende oder wartende"):
        client_cache.cleanup_client_borg_caches("reset", [{"host_id": host.id, "name": "repository-21"}])
