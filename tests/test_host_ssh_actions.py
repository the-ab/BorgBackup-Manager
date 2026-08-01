from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.gettempdir()) / f"bbm-host-ssh-actions-{os.getpid()}"
shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
os.environ.setdefault("BBM_DATA_DIR", str(TEST_DATA_DIR))
os.environ.setdefault("BBM_DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.runner import Command, host_ssh_action_command
from app import service

from tests.auth_helpers import admin_headers

AUTH = admin_headers()
HOST_KEY = "host.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEtesthostkeymaterial"


def _host(client: TestClient, name: str = "ssh-action-host") -> dict:
    response = client.post(
        "/api/hosts",
        headers=AUTH,
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
        host = _host(client)
        created = client.post(
            "/api/host-ssh-actions",
            headers=AUTH,
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

        listed = client.get("/api/host-ssh-actions", headers=AUTH)
        assert listed.status_code == 200
        assert any(item["id"] == action["id"] for item in listed.json())

        updated = client.put(
            f"/api/host-ssh-actions/{action['id']}",
            headers=AUTH,
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

        started = client.post(f"/api/host-ssh-actions/{action['id']}/run", headers=AUTH)
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        deadline = time.monotonic() + 2
        payload = None
        while time.monotonic() < deadline:
            payload = client.get(f"/api/runs/{run_id}", headers=AUTH).json()
            if payload["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert payload is not None
        assert payload["status"] == "success"
        assert payload["action"] == "ssh-command"
        assert payload["job_name"] == f"{host['name']} · NFS mount"
        assert payload["output"] == "mounted"

        deleted = client.delete(f"/api/host-ssh-actions/{action['id']}", headers=AUTH)
        assert deleted.status_code == 204


def test_saved_ssh_action_requires_persisted_action_not_ad_hoc_command():
    with TestClient(app) as client:
        response = client.post(
            "/api/host-ssh-actions/999999/run",
            headers=AUTH,
            json={"command": "rm -rf /"},
        )
    assert response.status_code == 404


def test_saved_ssh_action_rejects_disabled_host():
    with TestClient(app) as client:
        host = _host(client, "disabled-ssh-action-host")
        action = client.post(
            "/api/host-ssh-actions",
            headers=AUTH,
            json={
                "host_id": host["id"], "name": "status", "command": "true",
                "timeout_seconds": 30, "enabled": True,
            },
        ).json()
        client.post(f"/api/hosts/{host['id']}/enabled", headers=AUTH, json={"enabled": False})
        started = client.post(f"/api/host-ssh-actions/{action['id']}/run", headers=AUTH)
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
