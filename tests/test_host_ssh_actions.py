from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from sqlalchemy import inspect

TEST_DATA_DIR = Path(tempfile.gettempdir()) / f"bbm-host-ssh-actions-{os.getpid()}"
shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
os.environ.setdefault("BBM_DATA_DIR", str(TEST_DATA_DIR))
os.environ.setdefault("BBM_DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.runner import Command, host_ssh_action_command
from app import security_store, service
from app.config import MASTER_KEY_PATH, SECURITY_DATABASE_PATH
from app.backups import _validate_security_backup_pair

from tests.auth_helpers import admin_headers

HOST_KEY = "host.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEtesthostkeymaterial"


def _host(client: TestClient, headers: dict[str, str], name: str = "ssh-action-host") -> dict:
    response = client.post(
        "/api/hosts",
        headers=headers,
        json={
            "name": name,
            "address": "10.0.0.44",
            "port": 22,
            "username": "backup",
            "host_key": HOST_KEY,
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_saved_ssh_action_crud_and_run(monkeypatch):
    async def successful_command(_command, **_kwargs):
        return 0, "mounted\n", ""

    monkeypatch.setattr(service, "execute", successful_command)
    monkeypatch.setattr(
        service,
        "host_ssh_action_command",
        lambda host, command, timeout: Command(
            ["printf", "%s", "mounted\\n"],
            preview=f"ssh {host.name} -- {command}",
            timeout_seconds=timeout,
        ),
    )

    with TestClient(app) as client:
        auth = admin_headers()
        host = _host(client, auth)
        created = client.post(
            "/api/host-ssh-actions",
            headers=auth,
            json={
                "host_id": host["id"],
                "name": "NFS mount",
                "command": "sudo -n mount /mnt/offline",
                "timeout_seconds": 45,
                "enabled": True,
            },
        )
        assert created.status_code == 201, created.text
        action = created.json()
        assert action["command"] == "sudo -n mount /mnt/offline"
        assert action["timeout_seconds"] == 45
        with sqlite3.connect(SECURITY_DATABASE_PATH) as connection:
            stored = connection.execute(
                "SELECT encrypted_command FROM host_ssh_actions WHERE id=?", (action["id"],)
            ).fetchone()
        assert stored is not None
        assert str(stored[0]).startswith("v2:")
        assert "sudo -n mount /mnt/offline" not in str(stored[0])
        with main_module.engine.connect() as connection:
            assert "host_ssh_actions" not in inspect(connection).get_table_names()

        listed = client.get("/api/host-ssh-actions", headers=auth)
        assert listed.status_code == 200
        assert any(item["id"] == action["id"] for item in listed.json())

        updated = client.put(
            f"/api/host-ssh-actions/{action['id']}",
            headers=auth,
            json={
                "host_id": host["id"],
                "name": "NFS mount",
                "command": "sudo -n mount -a",
                "timeout_seconds": 60,
                "enabled": True,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["command"] == "sudo -n mount -a"

        started = client.post(f"/api/host-ssh-actions/{action['id']}/run", headers=auth)
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        deadline = time.monotonic() + 2
        payload = None
        while time.monotonic() < deadline:
            payload = client.get(f"/api/runs/{run_id}", headers=auth).json()
            if payload["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert payload is not None
        assert payload["status"] == "success"
        assert payload["action"] == "ssh-command"
        assert payload["job_name"] == f"{host['name']} · NFS mount"
        assert payload["output"] == "mounted"

        deleted = client.delete(f"/api/host-ssh-actions/{action['id']}", headers=auth)
        assert deleted.status_code == 204


def test_saved_ssh_action_requires_persisted_action_not_ad_hoc_command():
    with TestClient(app) as client:
        auth = admin_headers()
        response = client.post(
            "/api/host-ssh-actions/999999/run",
            headers=auth,
            json={"command": "rm -rf /"},
        )
    assert response.status_code == 404


def test_saved_ssh_action_rejects_disabled_host():
    with TestClient(app) as client:
        auth = admin_headers()
        host = _host(client, auth, "disabled-ssh-action-host")
        action = client.post(
            "/api/host-ssh-actions",
            headers=auth,
            json={
                "host_id": host["id"], "name": "status", "command": "true",
                "timeout_seconds": 30, "enabled": True,
            },
        ).json()
        client.post(f"/api/hosts/{host['id']}/enabled", headers=auth, json={"enabled": False})
        started = client.post(f"/api/host-ssh-actions/{action['id']}/run", headers=auth)
    assert started.status_code == 409


def test_host_ssh_action_command_uses_strict_controller_ssh_and_timeout(monkeypatch):
    monkeypatch.setattr(
        "app.runner.get_system_secret",
        lambda name, default=None: "TEST-CONTROLLER-PRIVATE-KEY" if name == "controller_private_key" else default,
    )
    host = main_module.Host(
        id=777, name="target", address="192.0.2.10", port=2222,
        username="root", enabled=True, host_key=HOST_KEY,
    )
    command = host_ssh_action_command(host, "mount /mnt/backup && findmnt /mnt/backup", 90)
    assert command.timeout_seconds == 90
    assert "BatchMode=yes" in command.argv
    assert "StrictHostKeyChecking=yes" in command.argv
    assert command.argv[-2] == "root@192.0.2.10"
    assert "mount /mnt/backup" in command.argv[-1]
    assert "sh" in command.argv[-1]


def test_saved_action_preview_never_contains_plaintext_command():
    host = main_module.Host(
        id=778, name="preview-target", address="192.0.2.11", port=22,
        username="root", enabled=True, host_key=HOST_KEY,
    )
    command = host_ssh_action_command(host, "token=do-not-store-in-run-preview", 60)
    assert "do-not-store-in-run-preview" not in command.preview
    assert command.preview == "Gespeicherte SSH-Aktion auf Gerät preview-target"


def test_manager_backup_completeness_verifies_encrypted_ssh_actions(tmp_path):
    security_store.initialize_security_store()
    action = security_store.create_host_ssh_action(
        host_id=990001,
        name="backup-verification",
        command="token=confidential-command",
        timeout_seconds=30,
        enabled=True,
    )
    try:
        result = _validate_security_backup_pair(
            SECURITY_DATABASE_PATH, MASTER_KEY_PATH, require_runtime_identity=True
        )
        assert result["host_ssh_actions"] >= 1

        copied_database = tmp_path / "security.db"
        with sqlite3.connect(SECURITY_DATABASE_PATH) as source, sqlite3.connect(copied_database) as target:
            source.backup(target)
        with sqlite3.connect(copied_database) as connection:
            connection.execute(
                "UPDATE host_ssh_actions SET encrypted_command='v2:not-a-valid-token' WHERE id=?",
                (action.id,),
            )
            connection.commit()

        import pytest
        with pytest.raises(ValueError, match="SSH-Aktion .* kann mit dem gesicherten Master-Key nicht entschlüsselt werden"):
            _validate_security_backup_pair(
                copied_database, MASTER_KEY_PATH, require_runtime_identity=True
            )
    finally:
        security_store.delete_host_ssh_action(action.id)
