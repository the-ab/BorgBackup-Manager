from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app import backups


def _prepare_complete_state(monkeypatch, tmp_path: Path) -> tuple[Path, bytes]:
    data = tmp_path / "data"
    data.mkdir()
    manager_db = data / "manager.db"
    with sqlite3.connect(manager_db) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('saved')")

    security_dir = data / "security"
    security_dir.mkdir()
    security_db = security_dir / "security.db"
    master_key = Fernet.generate_key()
    cipher = Fernet(master_key)
    with sqlite3.connect(security_db) as connection:
        connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
        connection.execute("INSERT INTO users(username) VALUES ('admin')")
        connection.execute("CREATE TABLE sessions(id INTEGER PRIMARY KEY, token_hash TEXT)")
        connection.execute("CREATE TABLE secrets(scope TEXT, name TEXT, encrypted_value TEXT)")
        for secret_name in sorted(backups._REQUIRED_SYSTEM_SECRET_NAMES):
            encrypted = "v2:" + cipher.encrypt(f"secret-{secret_name}".encode()).decode("ascii")
            connection.execute("INSERT INTO secrets VALUES ('system', ?, ?)", (secret_name, encrypted))
        repository_secret = "v2:" + cipher.encrypt(b"repository-passphrase").decode("ascii")
        connection.execute("INSERT INTO secrets VALUES ('repository:1', 'passphrase', ?)", (repository_secret,))
    (security_dir / "master.key").write_bytes(master_key + b"\n")

    settings = data / "settings.json"
    settings.write_text('{"density":"compact"}', encoding="utf-8")
    notifications = data / "notifications.json"
    notifications.write_text('{"enabled":true}', encoding="utf-8")

    monkeypatch.setattr(backups, "DATA_DIR", data)
    monkeypatch.setattr(backups, "BACKUP_DIR", data / "backups")
    monkeypatch.setattr(backups, "DATABASE_URL", f"sqlite:///{manager_db}")
    monkeypatch.setattr(backups, "SECURITY_DATABASE_PATH", security_db)
    monkeypatch.setattr(backups, "SETTINGS_PATH", settings)
    monkeypatch.setattr(backups, "NOTIFICATION_SETTINGS_PATH", notifications)
    return data, master_key


def test_manager_backup_contains_complete_recovery_pair(monkeypatch, tmp_path: Path):
    _prepare_complete_state(monkeypatch, tmp_path)
    backup = backups.create_full_backup("1.3.1", "complete", "correct horse battery staple")

    with backups.plain_backup_file(backup, "correct horse battery staple") as plain:
        with zipfile.ZipFile(plain) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))

    assert manifest["format_version"] == 7
    assert manifest["security_inventory"]["users"] == 1
    assert manifest["security_inventory"]["secrets"] == len(backups._REQUIRED_SYSTEM_SECRET_NAMES) + 1
    assert {
        "data/manager.db",
        "data/security/security.db",
        "data/security/master.key",
        "data/settings.json",
        "data/notifications.json",
        "migration.env",
    } <= names
    assert "authorized_keys" in manifest["regenerable_not_included"]
    staging, restored_manifest = backups.prepare_full_backup_restore(backup, "correct horse battery staple")
    try:
        assert restored_manifest["format_version"] == 7
    finally:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)


def test_manager_backup_refuses_missing_master_key(monkeypatch, tmp_path: Path):
    data, _key = _prepare_complete_state(monkeypatch, tmp_path)
    (data / "security" / "master.key").unlink()
    with pytest.raises(ValueError, match="Master-Key fehlt"):
        backups.create_full_backup("1.3.1", "broken", "correct horse battery staple")
    assert not list((data / "backups").glob("*.bbm"))


def test_manager_backup_refuses_mismatched_master_key(monkeypatch, tmp_path: Path):
    data, _key = _prepare_complete_state(monkeypatch, tmp_path)
    (data / "security" / "master.key").write_bytes(Fernet.generate_key() + b"\n")
    with pytest.raises(ValueError, match="nicht entschlüsselt"):
        backups.create_full_backup("1.3.1", "broken", "correct horse battery staple")


def test_restore_rejects_manager_backup_without_security_pair(monkeypatch, tmp_path: Path):
    data, _key = _prepare_complete_state(monkeypatch, tmp_path)
    source = tmp_path / "complete.zip"
    backups._write_plain_backup(source, "1.3.1", "complete")
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as output_archive:
        for item in input_archive.infolist():
            if item.filename == "data/security/master.key":
                continue
            output_archive.writestr(item, input_archive.read(item.filename))
    with pytest.raises(ValueError, match="Master-Key fehlt"):
        backups.prepare_full_backup_restore(broken)
    assert (data / "security" / "master.key").is_file()
