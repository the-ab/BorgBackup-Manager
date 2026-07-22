from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.gettempdir()) / f"bbm-test-data-{os.getpid()}"
shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
os.environ.setdefault("BBM_ADMIN_TOKEN", "test-token")
os.environ.setdefault("BBM_ALLOW_LEGACY_TOKEN_AUTH", "1")
os.environ.setdefault("BBM_DATA_DIR", str(TEST_DATA_DIR))
os.environ.setdefault("BBM_DATABASE_URL", "sqlite://")

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main_module
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import BackupSchedule, Host, HostRepositoryAccess, Job, Repository, Run
from app import runner, service
from app.vault import get_repository_secret


AUTH = {"Authorization": "Bearer test-token"}
HOST_KEY = "host.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEtesthostkeymaterial"

BROWSER = {"X-BBM-Request": "1"}


def wait_for_run_terminal(client: TestClient, run_id: int, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}", headers=AUTH)
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] not in {"queued", "running"}:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish within {timeout} seconds")


def test_health_is_public():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_health_is_degraded_when_repository_sshd_is_required_but_missing(monkeypatch):
    monkeypatch.setattr(main_module, "HEALTH_REQUIRE_SSHD", True)
    monkeypatch.setattr(main_module, "repository_sshd_listening", lambda: False)
    with TestClient(app) as client:
        compatible = client.get("/api/health")
        strict = client.get("/api/health/strict")
        unauthorized_detail = client.get("/api/system/health")
        detail = client.get("/api/system/health", headers=AUTH)
    assert compatible.status_code == 200
    assert compatible.json() == {"status": "degraded"}
    assert strict.status_code == 503
    assert strict.json() == {"status": "degraded"}
    assert unauthorized_detail.status_code == 401
    assert detail.status_code == 503
    assert detail.json()["status"] == "degraded"
    assert detail.json()["repository_sshd"] is False


def test_api_requires_token():
    with TestClient(app) as client:
        assert client.get("/api/hosts").status_code == 401


def test_host_key_rejects_multiple_known_hosts_lines():
    with TestClient(app) as client:
        response = client.post(
            "/api/hosts", headers=AUTH,
            json={
                "name": "bad-key", "address": "10.0.0.9", "port": 22,
                "username": "backup", "host_key": HOST_KEY, "enabled": True,
                "host_key": "host ssh-ed25519 AAAA\nattacker ssh-ed25519 BBBB",
            },
        )
    assert response.status_code == 422


def test_repository_rejects_reserved_environment_override():
    with TestClient(app) as client:
        response = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": "bad environment", "managed": False, "location": "/tmp/repo",
                "extra_env": {"BORG_RSH": "unsafe"},
            },
        )
    assert response.status_code == 422


def test_create_host():
    with TestClient(app) as client:
        response = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "server", "address": "10.0.0.2", "port": 22, "username": "backup", "host_key": HOST_KEY, "enabled": True},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "server"


def test_host_can_be_edited_and_connection_change_resets_repository_access():
    with TestClient(app) as client:
        created = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "editable", "address": "10.0.0.20", "port": 22, "username": "backup", "host_key": HOST_KEY, "enabled": True},
        ).json()
        with SessionLocal() as db:
            row = db.get(main_module.Host, created["id"])
            row.repository_ready = True
            db.commit()

        response = client.put(
            f"/api/hosts/{created['id']}", headers=AUTH,
            json={
                "name": "editable-renamed", "address": "10.0.0.21", "port": 2222,
                "username": "backup", "host_key": HOST_KEY, "enabled": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["name"] == "editable-renamed"
    assert response.json()["enabled"] is False
    assert response.json()["repository_ready"] is False


def test_manual_backup_is_queued_on_the_application_event_loop(monkeypatch):
    async def successful_command(_command, **_kwargs):
        return 0, "backup complete", ""

    monkeypatch.setattr(service, "execute", successful_command)

    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={
                "name": "manual-server", "address": "10.0.0.3", "port": 22,
                "username": "backup", "host_key": HOST_KEY, "enabled": True,
            },
        )
        assert host.status_code == 201
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": "manual-repository", "location": "/srv/borg/repository",
                "passphrase_env": None, "managed": False, "extra_env": {},
            },
        )
        assert repository.status_code == 201
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": "manual-job", "host_id": host.json()["id"],
                "repository_id": repository.json()["id"], "source_paths": ["/home"],
                "exclude_patterns": [], "schedule": None, "compression": "zstd,6",
                "prune_options": {}, "enabled": True,
            },
        )
        assert job.status_code == 201

        response = client.post(
            f"/api/jobs/{job.json()['id']}/actions/backup", headers=AUTH,
        )
        assert response.status_code == 202

        run_id = response.json()["run_id"]
        for _ in range(20):
            run = client.get(f"/api/runs/{run_id}", headers=AUTH)
            if run.json()["status"] == "success":
                break
            time.sleep(0.01)

        assert run.json()["status"] == "success"
        assert run.json()["output"] == "backup complete"


def test_managed_repository_is_derived_and_secret_is_encrypted(monkeypatch):
    queued = []
    monkeypatch.setattr(main_module, "queue_repository_init", lambda repository_id: queued.append(repository_id) or 1)

    with TestClient(app) as client:
        response = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": "Managed Main", "managed": True,
                "passphrase": "not stored in plaintext", "extra_env": {},
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["managed"] is True
    assert body["initialized"] is False
    assert body["has_passphrase"] is True
    assert body["location"].startswith("ssh://borg@")
    assert queued == [body["id"]]

    with SessionLocal() as db:
        row = db.scalar(select(Repository).where(Repository.id == body["id"]))
        assert row is not None
        assert row.storage_path.replace("\\", "/").endswith("managed-main-612a8600")
        assert row.encrypted_passphrase is None
        assert get_repository_secret(row, "passphrase") == "not stored in plaintext"


def test_managed_repository_can_be_created_unencrypted(monkeypatch):
    queued = []
    monkeypatch.setattr(main_module, "queue_repository_init", lambda repository_id: queued.append(repository_id) or 1)

    with TestClient(app) as client:
        response = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "Managed Plain", "managed": True, "encryption_mode": "none", "extra_env": {}},
        )

    assert response.status_code == 201
    assert response.json()["encryption_mode"] == "none"
    assert response.json()["has_passphrase"] is False
    assert queued == [response.json()["id"]]


def test_repository_can_be_edited_without_reentering_stored_passphrase(monkeypatch):
    monkeypatch.setattr(main_module, "queue_repository_init", lambda _repository_id: 1)
    with TestClient(app) as client:
        created = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": "Editable managed repository", "managed": True,
                "encryption_mode": "repokey-blake2", "passphrase": "retained secret",
            },
        ).json()
        response = client.put(
            f"/api/repositories/{created['id']}", headers=AUTH,
            json={
                "name": "Renamed managed repository", "managed": True,
                "encryption_mode": "repokey-blake2", "passphrase": None,
            },
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed managed repository"
    assert response.json()["has_passphrase"] is True


def test_managed_keyfile_is_captured_encrypted_and_removed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(runner, "REPOSITORY_KEYFILES_PATH", tmp_path)

    async def successful_init(command, **_kwargs):
        key_path = Path(command.env["BORG_KEY_FILE"])
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text("SECRET-BORG-KEYFILE", encoding="utf-8")
        return 0, "repository initialized", ""

    monkeypatch.setattr(service, "execute", successful_init)
    with TestClient(app) as client:
        response = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": "Managed Keyfile", "managed": True, "encryption_mode": "keyfile-blake2",
                "passphrase": "keyfile passphrase", "extra_env": {},
            },
        )
        assert response.status_code == 201
        repository_id = response.json()["id"]
        for _ in range(30):
            current = next(
                item for item in client.get("/api/repositories", headers=AUTH).json()
                if item["id"] == repository_id
            )
            if current["initialized"]:
                break
            time.sleep(0.01)

    assert current["initialized"] is True
    with SessionLocal() as db:
        row = db.get(Repository, repository_id)
        assert row.encrypted_keyfile is None
        assert get_repository_secret(row, "keyfile") == "SECRET-BORG-KEYFILE"
    assert list(tmp_path.iterdir()) == []


def test_dashboard_counts_repositories():
    with TestClient(app) as client:
        response = client.get("/api/dashboard", headers=AUTH)

    assert response.status_code == 200
    assert "repositories" in response.json()["counts"]
    assert "repository_size_bytes" in response.json()["counts"]


def test_run_output_has_sequential_run_id_and_job_name():
    with SessionLocal() as db:
        host = Host(name="run-name-host", address="127.0.0.1", username="root")
        repository = Repository(name="run-name-repo", location="/tmp/run-name-repo", initialized=True)
        db.add_all([host, repository]); db.flush()
        job = Job(
            name="named-job", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/tmp"]', exclude_patterns_json="[]",
        )
        db.add(job); db.flush()
        first = Run(job_id=job.id, action="backup", status="success")
        second = Run(job_id=job.id, action="info", status="success")
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id

    with TestClient(app) as client:
        runs = client.get("/api/runs?limit=500", headers=AUTH).json()
    by_id = {row["id"]: row for row in runs}
    assert second_id > first_id
    assert by_id[first_id]["job_name"] == "named-job"
    assert by_id[second_id]["job_name"] == "named-job"


def test_job_can_be_updated_from_webui_contract():
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "job-edit-host", "address": "10.0.0.30", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "job-edit-repo", "managed": False, "location": "/tmp/edit-repo"},
        ).json()
        created = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": "job-before-edit", "host_id": host["id"], "repository_id": repository["id"],
                "source_paths": ["/home"], "compression": "lz4", "prune_options": {},
            },
        ).json()
        response = client.put(
            f"/api/jobs/{created['id']}", headers=AUTH,
            json={
                "name": "job-after-edit", "host_id": host["id"], "repository_id": repository["id"],
                "source_paths": ["/home", "/etc"], "exclude_patterns": ["*.tmp"],
                "schedule": "15 3 * * *", "compression": "zstd,10",
                "prune_options": {"daily": 5}, "enabled": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["name"] == "job-after-edit"
    assert response.json()["source_paths"] == ["/home", "/etc"]
    assert response.json()["enabled"] is False


def test_running_job_publishes_live_output_and_can_be_cancelled(monkeypatch):
    async def slow_command(_command, on_output=None, **_kwargs):
        if on_output:
            await on_output("stdout", "live line\n")
        await service.asyncio.sleep(30)
        return 0, "live line\n", ""

    monkeypatch.setattr(service, "execute", slow_command)
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "live-host", "address": "10.0.0.31", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "live-repo", "managed": False, "location": "/tmp/live-repo"},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={"name": "live-job", "host_id": host["id"], "repository_id": repository["id"], "source_paths": ["/srv"]},
        ).json()
        started = client.post(f"/api/jobs/{job['id']}/actions/backup", headers=AUTH).json()
        run_id = started["run_id"]
        for _ in range(30):
            live = client.get(f"/api/runs/{run_id}", headers=AUTH).json()
            if "live line" in live["output"]:
                break
            time.sleep(0.01)
        cancelled = client.post(f"/api/runs/{run_id}/cancel", headers=AUTH)
        for _ in range(30):
            final = client.get(f"/api/runs/{run_id}", headers=AUTH).json()
            if final["status"] == "cancelled":
                break
            time.sleep(0.01)

    assert "live line" in live["output"]
    assert cancelled.status_code == 202
    assert final["status"] == "cancelled"


def test_old_borg_client_has_security_warning_instead_of_block():
    diagnosis = main_module.diagnose_run(
        "borg 1.2.4",
        "WARNUNG: Borg 1.2.0 bis 1.2.4 besitzen eine bekannte Archive-Spoofing-Schwachstelle.",
    )

    assert diagnosis["title"] == "Borg-Version mit kritischer Sicherheitswarnung"


def test_borg_connection_error_has_actionable_diagnosis():
    diagnosis = main_module.diagnose_run("", "Connection closed by remote host. Is borg working on the server?")

    assert diagnosis["title"] == "Repository-SSH vor Banner beendet"
    assert "repository_sshd" in diagnosis["action"]
    assert "Hostschlüssel" in diagnosis["detail"]


def test_borg_connection_diagnosis_distinguishes_ssh_stages():
    during_auth = main_module.diagnose_run(
        "Remote: debug1: Remote protocol version 2.0, remote software version OpenSSH_9.2",
        "Connection closed by remote host. Is borg working on the server?",
    )
    after_auth = main_module.diagnose_run(
        "Remote: debug1: Remote protocol version 2.0\nAuthenticated to backup.example",
        "Connection closed by remote host. Is borg working on the server?",
    )

    assert during_auth["title"] == "Repository-SSH-Aushandlung oder Anmeldung beendet"
    assert after_auth["title"] == "Repository-SSH angemeldet, Borg-Server beendet"


def test_run_diagnosis_distinguishes_source_device_cache_lock_from_repository_lock():
    diagnosis = main_module.diagnose_run(
        "",
        "Failed to create/acquire the lock "
        "/root/.cache/borg/17102d27605c6ee4fa9f80275082fa87a41e3667c4e737a67e3c8aad3192d7fd/"
        "lock.exclusive (timeout).",
    )

    assert diagnosis["title"] == "Lokaler Borg-Cache auf dem Gerät gesperrt"
    assert "/root" in diagnosis["detail"]
    assert "nicht im Repository" in diagnosis["detail"]
    assert "kein borg break-lock" in diagnosis["action"]

    manager_diagnosis = main_module.diagnose_run(
        "",
        "Failed to create/acquire the lock /repositories/.cache/borg/abc/lock.exclusive (timeout).",
    )
    assert manager_diagnosis["title"] == "Repository gesperrt"


def test_storage_guard_blocks_managed_backup(monkeypatch):
    monkeypatch.setattr(service, "managed_repository_present", lambda repository: True)
    monkeypatch.setattr(service, "repository_storage_status", lambda repository, settings: {
        "path": repository.storage_path, "total": 100, "used": 96, "free": 4, "percent": 96.0,
        "guard_enabled": True, "guard_threshold_percent": 95, "guard_source": "global",
        "guard_blocked": True,
    })
    with SessionLocal() as db:
        host = Host(name="guard-host", address="10.0.0.40", username="root", repository_ready=True)
        repository = Repository(
            name="guard-repo", location="ssh://borg@example/./guard", storage_path="/repositories/guard",
            initialized=True, encryption_mode="none",
        )
        db.add_all([host, repository]); db.flush()
        job = Job(
            name="guard-job", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/home"]', exclude_patterns_json="[]",
        )
        db.add(job); db.flush()
        job.archive_prefix = f"bbm-job-{job.id}-"
        db.add(HostRepositoryAccess(
            host_id=host.id, repository_id=repository.id,
            public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGuardKey bbm-test",
        ))
        db.commit(); job_id = job.id

    try:
        service.queue_job_action(job_id, "backup")
    except ValueError as exc:
        assert "Speicherplatz-Sperre" in str(exc)
    else:
        raise AssertionError("storage guard did not block backup")


def test_restart_marks_active_runs_as_failed():
    with SessionLocal() as db:
        run = Run(action="backup", status="running")
        db.add(run); db.commit(); run_id = run.id

    main_module.recover_interrupted_runs()

    with SessionLocal() as db:
        recovered = db.get(Run, run_id)
        assert recovered.status == "failed"
        assert "restarted" in recovered.error
        assert recovered.finished_at is not None


def test_repository_access_can_be_bootstrapped_from_webui(monkeypatch, tmp_path: Path):
    host_key = tmp_path / "ssh_host_ed25519_key.pub"
    host_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJfHostKey manager\n", encoding="utf-8")
    authorized_keys = tmp_path / "authorized_keys"
    authorized_keys.write_text(
        'restrict,command="/usr/local/bin/bbm-borg-serve" ssh-ed25519 AAAALEGACY legacy\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "REPOSITORY_HOST_KEY_PUBLIC_PATH", host_key)
    monkeypatch.setattr(service, "REPOSITORY_AUTHORIZED_KEYS_PATH", authorized_keys)

    repository_id = 0

    async def successful_bootstrap(command):
        assert "bbm_repository_${repository_id}_ed25519" in command.argv[-1]
        assert command.argv[-1].rstrip().endswith(str(repository_id))
        return 0, (
            f"BBM_REPOSITORY_KEY {repository_id} "
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDeviceKey backup@test\n"
        ), ""

    monkeypatch.setattr(service, "execute", successful_bootstrap)

    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={
                "name": "bootstrap-server", "address": "10.0.0.8", "port": 22,
                "username": "backup", "host_key": HOST_KEY, "enabled": True,
            },
        )
        with SessionLocal() as db:
            repository = Repository(
                name="bootstrap-repository",
                location="ssh://borg@manager:2222/./bootstrap-repo",
                storage_path="/repositories/bootstrap-repo",
                initialized=True,
                encryption_mode="none",
                extra_env_json="{}",
            )
            db.add(repository); db.flush()
            repository_id = repository.id
            job = Job(
                name="bootstrap-job",
                host_id=host.json()["id"],
                repository_id=repository.id,
                source_paths_json='["/srv"]',
                exclude_patterns_json="[]",
                archive_prefix="bbm-bootstrap-",
                create_options_json="{}",
            )
            db.add(job); db.commit()
        service.sync_repository_access_assignments()
        response = client.post(
            f"/api/hosts/{host.json()['id']}/bootstrap-repository", headers=AUTH,
        )
        refreshed = client.get("/api/hosts", headers=AUTH).json()

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["configured"] == 1
    content = authorized_keys.read_text(encoding="utf-8")
    assert "AAAAC3NzaC1lZDI1NTE5AAAAIDeviceKey" in content
    assert "AAAALEGACY" not in content
    assert 'command="/usr/local/bin/bbm-borg-serve --repository /repositories/bootstrap-repo"' in content
    assert f"bbm-access-h{host.json()['id']}-r{repository_id}" in content
    assert next(item for item in refreshed if item["id"] == host.json()["id"])["repository_ready"] is True



def test_managed_repository_allows_assignment_to_multiple_devices(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    monkeypatch.setattr(main_module, "queue_repository_init", lambda _repository_id: 1)
    with TestClient(app) as client:
        first_host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"first-{suffix}", "address": "10.9.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        second_host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"second-{suffix}", "address": "10.9.0.2", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"shared-repository-{suffix}", "managed": True,
                "encryption_mode": "repokey-blake2", "passphrase": "secure secret",
            },
        ).json()
        first_job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"first-job-{suffix}", "host_id": first_host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        )
        second_job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"second-job-{suffix}", "host_id": second_host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        )

    assert first_job.status_code == 201
    assert second_job.status_code == 201
    with SessionLocal() as db:
        accesses = db.scalars(
            select(HostRepositoryAccess).where(HostRepositoryAccess.repository_id == repository["id"])
        ).all()
    assert {row.host_id for row in accesses} == {first_host["id"], second_host["id"]}


def test_completed_run_history_does_not_block_job_deletion():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"delete-host-{suffix}", "address": "10.20.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"delete-repo-{suffix}", "managed": False,
                "location": f"/tmp/delete-repo-{suffix}", "extra_env": {},
            },
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"delete-job-{suffix}", "host_id": host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        ).json()
        with SessionLocal() as db:
            run = Run(
                job_id=job["id"], repository_id=repository["id"], action="backup",
                status="success", command_preview="borg create", output="ok", error="",
            )
            db.add(run); db.commit(); run_id = run.id

        response = client.delete(f"/api/jobs/{job['id']}", headers=AUTH)

    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Job, job["id"]) is None
        run = db.get(Run, run_id)
        assert run is not None
        assert run.job_id is None
        assert run.job_name_snapshot == job["name"]


def test_active_run_still_blocks_job_deletion():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"active-host-{suffix}", "address": "10.20.0.2", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"active-repo-{suffix}", "managed": False, "location": f"/tmp/active-{suffix}"},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"active-job-{suffix}", "host_id": host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        ).json()
        with SessionLocal() as db:
            run = Run(job_id=job["id"], repository_id=repository["id"], action="backup", status="running")
            db.add(run); db.commit(); run_id = run.id
        response = client.delete(f"/api/jobs/{job['id']}", headers=AUTH)
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            run.status = "failed"
            db.commit()

    assert response.status_code == 409
    assert "queued or running" in response.json()["detail"]


def test_repository_archive_overview_assigns_job_owners_and_accepts_colons(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    commands = []

    async def archive_listing(repository_id, command):
        commands.append((repository_id, command.argv[-1]))
        return 0, json.dumps({
            "archives": [
                {"name": "bbm-job-900-client-2026-07-13T22:00:00", "id": "a1", "start": "2026-07-13T22:00:01"},
                {"name": "legacy-client-2026-07-12T22:00:00", "id": "a2", "start": "2026-07-12T22:00:01"},
            ]
        }), ""

    monkeypatch.setattr(main_module, "execute_interactive", archive_listing)
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"archive-host-{suffix}", "address": "10.30.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"archive-repo-{suffix}", "managed": False, "location": f"/tmp/archive-{suffix}"},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"archive-job-{suffix}", "host_id": host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        ).json()
        # Make the mocked archive name belong to this actual job.
        owned_name = f"{job['archive_prefix']}client-2026-07-13T22:00:00"

        async def actual_listing(repository_id, command):
            commands.append((repository_id, command.argv[-1]))
            return 0, json.dumps({"archives": [
                {"name": owned_name, "id": "a1", "start": "2026-07-13T22:00:01"},
                {"name": "legacy-client-2026-07-12T22:00:00", "id": "a2", "start": "2026-07-12T22:00:01"},
            ]}), ""

        monkeypatch.setattr(main_module, "execute_interactive", actual_listing)
        response = client.get(f"/api/jobs/{job['id']}/archives?all_archives=true", headers=AUTH)

    assert response.status_code == 200
    archives = response.json()["archives"]
    assert archives[0]["name"] == owned_name
    assert archives[0]["job_id"] == job["id"]
    assert archives[0]["legacy"] is False
    assert archives[1]["legacy"] is True
    assert "--glob-archives" not in commands[-1][1]


def test_existing_repository_can_be_discovered_and_imported(monkeypatch, tmp_path):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    repository_root = tmp_path / "repositories"
    existing = repository_root / f"existing-{suffix}"
    existing.mkdir(parents=True)
    (existing / "config").write_text("[repository]\nid = abcdef123456\n", encoding="utf-8")
    monkeypatch.setattr(main_module, "REPOSITORY_ROOT", repository_root)

    async def valid_repository(_repository_id, _command):
        return 0, '{"repository": {"id": "abcdef123456"}}', ""

    monkeypatch.setattr(main_module, "execute_interactive", valid_repository)
    with TestClient(app) as client:
        discovered = client.get("/api/repositories/discover", headers=AUTH)
        imported = client.post(
            "/api/repositories/import", headers=AUTH,
            json={
                "name": f"Imported {suffix}",
                "directory_name": existing.name,
                "encryption_mode": "none",
            },
        )
        discovered_after = client.get("/api/repositories/discover", headers=AUTH)

    assert discovered.status_code == 200
    assert any(item["directory_name"] == existing.name for item in discovered.json())
    assert imported.status_code == 201
    assert imported.json()["managed"] is True
    assert imported.json()["initialized"] is True
    assert all(item["directory_name"] != existing.name for item in discovered_after.json())


def test_host_deletion_removes_repository_access_rows():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"orphan-host-{suffix}", "address": "10.40.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"orphan-repo-{suffix}", "managed": False, "location": f"/tmp/orphan-{suffix}"},
        ).json()
        with SessionLocal() as db:
            db.add(HostRepositoryAccess(host_id=host["id"], repository_id=repository["id"], public_key="ssh-ed25519 AAAA"))
            db.commit()

        response = client.delete(f"/api/hosts/{host['id']}", headers=AUTH)

    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Host, host["id"]) is None
        assert db.get(Repository, repository["id"]) is not None
        assert db.scalar(
            select(HostRepositoryAccess).where(HostRepositoryAccess.host_id == host["id"])
        ) is None


def test_repository_deletion_detaches_completed_history_and_removes_access():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"repo-delete-host-{suffix}", "address": "10.40.0.2", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"repo-delete-{suffix}", "managed": False, "location": f"/tmp/repo-delete-{suffix}"},
        ).json()
        with SessionLocal() as db:
            access = HostRepositoryAccess(
                host_id=host["id"], repository_id=repository["id"], public_key="ssh-ed25519 AAAA"
            )
            run = Run(
                repository_id=repository["id"], action="check", status="success",
                command_preview="borg check", output="ok", error="",
            )
            db.add_all([access, run])
            db.commit()
            run_id = run.id

        response = client.delete(f"/api/repositories/{repository['id']}", headers=AUTH)

    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Repository, repository["id"]) is None
        assert db.scalar(
            select(HostRepositoryAccess).where(HostRepositoryAccess.repository_id == repository["id"])
        ) is None
        run = db.get(Run, run_id)
        assert run is not None
        assert run.repository_id is None


def test_recreated_job_never_reuses_deleted_archive_prefix():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"prefix-host-{suffix}", "address": "10.50.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"prefix-repo-{suffix}", "managed": False, "location": f"/tmp/prefix-{suffix}"},
        ).json()
        first = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"prefix-first-{suffix}", "host_id": host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        ).json()
        assert client.delete(f"/api/jobs/{first['id']}", headers=AUTH).status_code == 204
        second = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"prefix-second-{suffix}", "host_id": host["id"],
                "repository_id": repository["id"], "source_paths": ["/srv"],
            },
        ).json()

    assert first["archive_prefix"] != second["archive_prefix"]
    assert first["archive_prefix"] == f"bbm-{first['id']}-"
    assert second["archive_prefix"] == f"bbm-{second['id']}-"
    assert second["id"] > first["id"]
    assert second["archive_prefixes"] == [second["archive_prefix"]]


def test_host_version_check_stores_warning_without_blocking(monkeypatch):
    async def fake_execute(_repository_id, _command):
        return 0, "borg 1.2.4\nBBM_BORG_VERSION=1.2.4\n", "WARNUNG: Archive-Spoofing-Schwachstelle\n"

    monkeypatch.setattr(main_module, "execute_interactive", fake_execute)
    with TestClient(app) as client:
        created = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "old-borg-client", "address": "10.0.0.88", "port": 22, "username": "root", "host_key": HOST_KEY, "enabled": True},
        ).json()
        response = client.post(f"/api/hosts/{created['id']}/check-version", headers=AUTH)
        host = client.get("/api/hosts", headers=AUTH).json()

    assert response.status_code == 200
    assert response.json()["supported"] is True
    assert response.json()["level"] == "critical"
    stored = next(item for item in host if item["id"] == created["id"])
    assert stored["borg_version"] == "1.2.4"
    assert stored["borg_version_status"] == "critical"


def test_run_json_prefers_unified_human_log():
    row = Run(
        id=999, action="backup", status="success", command_preview="technical command",
        output="stdout", error="stderr", log_output="human readable borg stats",
    )
    payload = main_module.run_json(row)
    assert payload["log_output"] == "human readable borg stats"
    assert payload["output"] == "stdout"
    assert payload["error"] == ""


def test_archive_browser_listing_parser_returns_direct_children_only():
    output = "\n".join([
        json.dumps({"path": "home/user/docs", "type": "d", "size": 0, "mtime": "2026-07-14T10:00:00"}),
        json.dumps({"path": "home/user/file.txt", "type": "file", "size": "123", "mtime": "2026-07-14T10:00:00"}),
        json.dumps({"path": "home/user/link", "type": "symlink", "size": 0, "source": "file.txt"}),
        json.dumps({"path": "home/user/docs/nested.txt", "type": "f", "size": 50}),
    ])
    entries = main_module.parse_archive_browser_listing(output, "home/user")
    assert [entry["name"] for entry in entries] == ["docs", "file.txt", "link"]
    assert entries[0]["type"] == "directory"
    assert entries[1]["size"] == 123
    assert entries[2]["type"] == "symlink"
    assert entries[2]["target"] == "file.txt"


def test_login_sets_secure_httponly_session_cookie_and_cookie_auth_works():
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/login", headers=BROWSER, json={"username": "admin", "password": "test-token"})
        assert response.status_code == 200
        cookie = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
        assert "expires=" in cookie.lower()
        status = client.get("/api/auth/status")
        assert status.status_code == 200
        assert status.json()["must_change_password"] is True
        assert client.get("/api/hosts").status_code == 403
        changed = client.post("/api/auth/change-password", headers=BROWSER, json={
            "current_password": "test-token",
            "new_password": "New-Test-Password-2026!",
            "new_password_confirm": "New-Test-Password-2026!",
        })
        assert changed.status_code == 200
        assert client.get("/api/auth/status").status_code == 401
        relogin = client.post("/api/auth/login", headers=BROWSER, json={
            "username": "admin", "password": "New-Test-Password-2026!",
        })
        assert relogin.status_code == 200
        assert client.get("/api/hosts").status_code == 200


def test_session_cookie_survives_reload_on_http_proxy_origin(monkeypatch):
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    with TestClient(app, base_url="http://testserver") as client:
        response = client.post("/api/auth/login", headers=BROWSER, json={"username": "admin", "password": "irrelevant"})
        assert response.status_code == 200
        cookie = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "expires=" in cookie.lower()
        assert "Secure" in cookie
        # A Secure cookie is intentionally not sent over plain HTTP.
        assert client.get("/api/auth/status").status_code == 401


def test_untrusted_forwarded_http_cannot_weaken_secure_cookie(monkeypatch):
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    with TestClient(app, base_url="https://internal-container") as client:
        response = client.post(
            "/api/auth/login",
            headers={**BROWSER, "x-forwarded-proto": "http"},
            json={"username": "admin", "password": "irrelevant"},
        )
        assert response.status_code == 200
        cookie = response.headers.get_list("set-cookie")[0]
        assert f"{main_module.SESSION_COOKIE_NAME}=" in cookie
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie


def test_secure_cookie_is_forced_even_for_http_upstream(monkeypatch):
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    with TestClient(app, base_url="http://internal-container") as client:
        response = client.post(
            "/api/auth/login",
            headers={**BROWSER, "x-forwarded-proto": "https"},
            json={"username": "admin", "password": "irrelevant"},
        )
        assert response.status_code == 200
        cookie = response.headers.get_list("set-cookie")[0]
        assert "Secure" in cookie


def test_auth_status_explains_missing_browser_cookie():
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.clear()
        response = client.get("/api/auth/status")
    assert response.status_code == 401
    assert main_module.SESSION_COOKIE_NAME in response.json()["detail"]
    assert "BBM_SESSION_COOKIE_SECURE" in response.json()["detail"]


def test_auth_status_reissues_valid_cookie_with_current_transport_attributes():
    with TestClient(app, base_url="https://testserver") as client:
        record = next(item for item in main_module.list_users() if item["username"] == "admin")
        user = main_module.AuthUser(
            id=record["id"], username=record["username"], role=record["role"],
            enabled=record["enabled"], must_change_password=record["must_change_password"],
        )
        token = main_module.create_session(user, 3600)
        client.cookies.clear()
        response = client.get("/api/auth/status", headers={"cookie": f"{main_module.SESSION_COOKIE_NAME}={token}"})
    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert f"{main_module.SESSION_COOKIE_NAME}={token}" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie


def test_duplicate_stale_session_cookie_does_not_hide_valid_session():
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    token = main_module.create_session(user, 3600)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.clear()
        response = client.get(
            "/api/auth/status",
            headers={"cookie": f"{main_module.SESSION_COOKIE_NAME}=stale-session; {main_module.SESSION_COOKIE_NAME}={token}"},
        )
    assert response.status_code == 200
    assert response.json()["username"] == user.username


def test_invalid_login_does_not_create_session():
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/login", headers=BROWSER, json={"username": "admin", "password": "wrong-token"})
        assert response.status_code == 401
        assert client.get("/api/auth/status").status_code == 401


def test_browser_responses_disable_stale_cache():
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["permissions-policy"]


def test_ready_is_public_and_does_not_depend_on_repository_banner(monkeypatch):
    monkeypatch.setattr(main_module, "HEALTH_REQUIRE_SSHD", True)
    monkeypatch.setattr(main_module, "repository_sshd_listening", lambda: False)
    with TestClient(app) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "ready"}


def test_run_json_prefers_explicit_client_version_over_file_names():
    row = Run(
        id=1001, action="backup", status="success",
        log_output="A home/releases/1.02.1/file\nBORG AUF CLIENT: 1.2.8\nA home/2.03.1/file",
    )
    payload = main_module.run_json(row)
    assert payload["borg_compatibility"]["version"] == "1.2.8"
    assert payload["borg_compatibility"]["level"] == "ok"


def test_live_run_does_not_show_transient_passphrase_diagnosis():
    row = Run(
        id=2001, action="backup", status="running",
        log_output="Passphrase helper initialized\nincorrect cache entry was ignored",
    )
    payload = main_module.run_json(row)
    assert payload["diagnosis"] is None


def test_passphrase_diagnosis_requires_explicit_final_borg_error():
    assert main_module.diagnose_run("passphrase helper initialized", "incorrect unrelated value") is None
    diagnosis = main_module.diagnose_run("", "Passphrase supplied in BORG_PASSCOMMAND is incorrect")
    assert diagnosis is not None
    assert diagnosis["title"] == "Passphrase abgelehnt"

    successful = Run(id=2003, action="backup", status="success", error="Passphrase supplied is incorrect")
    assert main_module.run_json(successful)["diagnosis"] is None


def test_run_list_can_be_filtered_by_failed_status():
    with SessionLocal() as db:
        failed = Run(action="backup", status="failed")
        success = Run(action="backup", status="success")
        db.add_all([failed, success])
        db.commit()
        failed_id, success_id = failed.id, success.id

    with TestClient(app) as client:
        response = client.get("/api/runs?status=failed&limit=500", headers=AUTH)

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert failed_id in ids
    assert success_id not in ids


def test_run_dates_are_serialized_as_utc_instants():
    row = Run(id=2002, action="backup", status="success")
    row.created_at = main_module.datetime(2026, 7, 16, 10, 30, 0)
    payload = main_module.run_json(row)
    assert payload["created_at"] == "2026-07-16T10:30:00Z"


def test_system_reports_europe_berlin_timezone():
    with TestClient(app) as client:
        response = client.get("/api/system", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/Berlin"


def test_admin_can_manage_users_and_operator_cannot_change_infrastructure():
    username = f"operator-{int(time.time() * 1000)}"
    password = "Operator-Test-Password-2026!"
    with TestClient(app, base_url="https://testserver") as admin_client:
        created = admin_client.post(
            "/api/users", headers=AUTH,
            json={
                "username": username,
                "password": password,
                "password_confirm": password,
                "role": "user",
                "must_change_password": False,
            },
        )
        assert created.status_code == 201
        user_id = created.json()["id"]

    with TestClient(app, base_url="https://testserver") as operator_client:
        login = operator_client.post("/api/auth/login", headers=BROWSER, json={"username": username, "password": password})
        assert login.status_code == 200
        assert login.json()["role"] == "user"
        assert operator_client.get("/api/jobs").status_code == 200
        denied = operator_client.post(
            "/api/hosts", headers=BROWSER,
            json={"name": "denied", "address": "127.0.0.1", "port": 22, "username": "root", "host_key": HOST_KEY, "enabled": True},
        )
        assert denied.status_code == 403
        assert operator_client.get("/api/runs?limit=10").status_code == 200
        assert operator_client.get("/api/runs/999999").status_code == 403
        assert operator_client.get("/api/mounts").status_code == 403
        assert operator_client.get("/api/repositories/999999/archives").status_code == 403
        assert operator_client.post("/api/jobs/999999/actions/backup", headers=BROWSER).status_code == 403
        assert operator_client.post("/api/repositories/999999/test", headers=BROWSER).status_code == 403
        assert operator_client.post("/api/runs/999999/cancel", headers=BROWSER).status_code == 403

    with TestClient(app) as admin_client:
        assert admin_client.delete(f"/api/users/{user_id}", headers=AUTH).status_code == 204


def test_session_token_is_only_stored_as_hash():
    from app.config import SECURITY_DATABASE_PATH

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/api/auth/login",
            headers=BROWSER,
            json={"username": "admin", "password": "New-Test-Password-2026!"},
        )
        assert response.status_code == 200
        raw_cookie = client.cookies.get(main_module.SESSION_COOKIE_NAME)
        assert raw_cookie
    import sqlite3
    with sqlite3.connect(SECURITY_DATABASE_PATH) as connection:
        rows = [item[0] for item in connection.execute("SELECT token_hash FROM sessions").fetchall()]
    assert raw_cookie not in rows
    assert all(len(value) == 64 for value in rows)


def test_archive_overview_can_include_and_mark_checkpoints(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    commands = []

    async def checkpoint_listing(repository_id, command):
        commands.append(command.argv[-1])
        return 0, json.dumps({"archives": [
            {"name": "job-checkpoint.checkpoint", "id": "cp1", "start": "2026-07-16T12:00:00"},
        ]}), ""

    monkeypatch.setattr(main_module, "execute_interactive", checkpoint_listing)
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"checkpoint-host-{suffix}", "address": "10.40.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"checkpoint-repo-{suffix}", "managed": False, "location": f"/tmp/checkpoint-{suffix}"},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={"name": f"checkpoint-job-{suffix}", "host_id": host["id"], "repository_id": repository["id"], "source_paths": ["/srv"]},
        ).json()
        response = client.get(
            f"/api/jobs/{job['id']}/archives?all_archives=true&consider_checkpoints=true",
            headers=AUTH,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["consider_checkpoints"] is True
    assert payload["archives"][0]["checkpoint"] is True
    assert "--consider-checkpoints" in commands[-1]


def test_external_repository_can_list_archives_without_backup_job(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    calls = []

    async def external_repository_command(repository_id, command):
        calls.append(command.preview)
        if "--glob-archives" in command.preview:
            return 0, json.dumps({
                "cache": {"stats": {"total_size": 10_000, "total_csize": 8_000, "unique_csize": 3_000}},
                "archives": [{
                    "name": "storagebox-2026-07-16T12:00:00",
                    "id": "ext1",
                    "start": "2026-07-16T12:00:00+00:00",
                    "end": "2026-07-16T12:02:00+00:00",
                    "stats": {
                        "nfiles": 42,
                        "original_size": 9_000,
                        "compressed_size": 7_000,
                        "deduplicated_size": 2_000,
                    },
                }],
            }), ""
        if " info " in f" {command.preview} ":
            return 0, json.dumps({"repository": {"id": "external-repo"}}), ""
        return 0, json.dumps({"archives": []}), ""

    async def queued_repository_command(command, **_kwargs):
        return await external_repository_command(None, command)

    monkeypatch.setattr(main_module, "execute_interactive", external_repository_command)
    monkeypatch.setattr(service, "execute", queued_repository_command)
    with TestClient(app) as client:
        response = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"storagebox-{suffix}",
                "managed": False,
                "location": "ssh://u123456@u123456.your-storagebox.de:23/./borg-repository",
                "generate_external_ssh_key": True,
                "scan_external_host_key": False,
                "external_known_hosts": "[u123456.your-storagebox.de]:23 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJf",
                "encryption_mode": "none",
            },
        )
        assert response.status_code == 201, response.text
        repository = response.json()
        assert repository["initialized"] is False
        assert repository["has_external_ssh_key"] is True
        assert repository["has_external_known_hosts"] is True
        assert repository["external_ssh_public_key"].startswith("ssh-ed25519 ")

        tested = client.post(f"/api/repositories/{repository['id']}/test", headers=AUTH)
        assert tested.status_code == 202, tested.text
        assert tested.json()["access_mode"] == "manager-local"
        assert wait_for_run_terminal(client, tested.json()["run_id"])["status"] == "success"
        archives = client.get(f"/api/repositories/{repository['id']}/archives", headers=AUTH)

    assert archives.status_code == 200, archives.text
    payload = archives.json()
    assert payload["job_id"] is None
    assert payload["access_mode"] == "manager-local"
    assert payload["archives"][0]["name"] == "storagebox-2026-07-16T12:00:00"
    assert payload["archives"][0]["job_id"] is None
    assert payload["archives"][0]["duration"] == 120.0
    assert payload["archives"][0]["nfiles"] == 42
    assert payload["archives"][0]["original_size"] == 9_000
    assert payload["archives"][0]["compressed_size"] == 7_000
    assert payload["archives"][0]["deduplicated_size"] == 2_000
    assert payload["repository_statistics"]["deduplicated_size"] == 3_000
    assert any("--glob-archives" in call for call in calls)
    assert len(calls) == 2  # connection test + one repository-wide archive statistics call

def test_external_repository_browser_works_without_job(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]

    async def external_command(repository_id, command):
        if " info " in f" {command.preview} ":
            return 0, json.dumps({"repository": {"id": "external-browser"}}), ""
        return 0, json.dumps({"path": "home", "type": "directory", "size": 0, "mtime": "2026-07-16T12:00:00"}) + "\n", ""

    async def queued_external_command(command, **_kwargs):
        return await external_command(None, command)

    monkeypatch.setattr(main_module, "execute_interactive", external_command)
    monkeypatch.setattr(service, "execute", queued_external_command)
    with TestClient(app) as client:
        repository_response = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"browser-storage-{suffix}",
                "managed": False,
                "location": "ssh://u123456@u123456.your-storagebox.de:23/./browser-repository",
                "generate_external_ssh_key": True,
                "scan_external_host_key": False,
                "external_known_hosts": "[u123456.your-storagebox.de]:23 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJf",
                "encryption_mode": "none",
            },
        )
        assert repository_response.status_code == 201, repository_response.text
        repository = repository_response.json()
        tested = client.post(f"/api/repositories/{repository['id']}/test", headers=AUTH)
        assert tested.status_code == 202, tested.text
        assert wait_for_run_terminal(client, tested.json()["run_id"])["status"] == "success"
        response = client.get(
            f"/api/repositories/{repository['id']}/archives/example-archive/browse",
            headers=AUTH,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repository_id"] == repository["id"]
    assert payload["access_mode"] == "manager-local"
    assert payload["entries"][0]["name"] == "home"


def test_legacy_external_access_client_is_retired_without_deleting_repository():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app):
        with SessionLocal() as db:
            host = Host(
                name=f"legacy-access-{suffix}", address="10.70.0.1", port=22,
                username="root", enabled=True,
            )
            db.add(host)
            db.flush()
            repository = Repository(
                name=f"legacy-external-{suffix}",
                location="ssh://legacy@example.invalid:23/./repository",
                encryption_mode="none",
                storage_path=None,
                access_host_id=host.id,
                external_ssh_key_path="~/.ssh/legacy",
                external_known_hosts_path="~/.ssh/legacy_known_hosts",
                initialized=True,
                extra_env_json="{}",
            )
            db.add(repository)
            db.commit()
            repository_id = repository.id

        main_module.migrate_legacy_external_repository_access()

        with SessionLocal() as db:
            repository = db.get(Repository, repository_id)
            assert repository is not None
            assert repository.access_host_id is None
            assert repository.external_ssh_key_path is None
            assert repository.external_known_hosts_path is None
            assert repository.initialized is False
            assert "Manager-SSH-Schlüssel" in repository.validation_error



def test_external_repository_failure_is_concise_and_details_are_persistent(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]

    async def failed_repository_command(repository_id, command):
        return 2, "", "\n".join([
            "Remote: debug1: Reading configuration data /etc/ssh/ssh_config",
            "Remote: debug2: KEX algorithms: curve25519-sha256",
            "Remote: debug1: Authenticating to u123@example:23 as 'u123'",
            "Remote: u123@example: Permission denied (publickey,password).",
            "Connection closed by remote host. Is borg working on the server?",
        ])

    async def queued_failed_command(command, **_kwargs):
        return await failed_repository_command(None, command)

    monkeypatch.setattr(service, "execute", queued_failed_command)
    with TestClient(app) as client:
        created = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"failed-storage-{suffix}",
                "managed": False,
                "location": "ssh://u123@example:23/./repo",
                "generate_external_ssh_key": True,
                "scan_external_host_key": False,
                "external_known_hosts": "[example]:23 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJf",
                "encryption_mode": "none",
            },
        ).json()
        tested = client.post(f"/api/repositories/{created['id']}/test", headers=AUTH)
        assert tested.status_code == 202, tested.text
        run = wait_for_run_terminal(client, tested.json()["run_id"])
        repositories = client.get("/api/repositories", headers=AUTH).json()

    assert run["status"] == "failed"
    stored = next(item for item in repositories if item["id"] == created["id"])
    assert "SSH-Anmeldung abgelehnt" in stored["validation_error"]
    assert "Permission denied" in stored["validation_details"]
    assert "KEX algorithms" not in stored["validation_details"]


def test_external_repository_size_uses_borg_info_without_backup_job(monkeypatch):
    from uuid import uuid4

    suffix = uuid4().hex[:8]

    async def repository_command(repository_id, command):
        return 0, json.dumps({
            "repository": {"id": "remote"},
            "cache": {"stats": {"unique_csize": 1234567, "unique_size": 2345678}},
        }), ""

    async def queued_repository_command(command, **_kwargs):
        return await repository_command(None, command)

    monkeypatch.setattr(main_module, "execute_interactive", repository_command)
    monkeypatch.setattr(service, "execute", queued_repository_command)
    with TestClient(app) as client:
        created = client.post(
            "/api/repositories", headers=AUTH,
            json={
                "name": f"sized-storage-{suffix}",
                "managed": False,
                "location": "ssh://u123@example:23/./repo",
                "generate_external_ssh_key": True,
                "scan_external_host_key": False,
                "external_known_hosts": "[example]:23 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJf",
                "encryption_mode": "none",
            },
        ).json()
        tested = client.post(f"/api/repositories/{created['id']}/test", headers=AUTH)
        assert tested.status_code == 202
        assert wait_for_run_terminal(client, tested.json()["run_id"])["status"] == "success"
        result = client.post(f"/api/repositories/{created['id']}/refresh-size", headers=AUTH)
        repositories = client.get("/api/repositories", headers=AUTH).json()

    assert result.status_code == 200, result.text
    assert result.json()["size_bytes"] == 1234567
    assert result.json()["size_type"] == "borg-deduplicated-compressed"
    stored = next(item for item in repositories if item["id"] == created["id"])
    assert stored["size_bytes"] == 1234567
    assert stored["size_checked_at"] is not None


def test_central_repository_schedule_marks_matching_jobs_and_rejects_unknown_targets():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={
                "name": f"schedule-host-{suffix}", "address": "10.80.0.1", "port": 22,
                "username": "root", "host_key": HOST_KEY, "enabled": True,
            },
        ).json()
        with SessionLocal() as db:
            repository = Repository(
                name=f"schedule-repo-{suffix}", location=f"/tmp/schedule-repo-{suffix}",
                initialized=True, encryption_mode="none", extra_env_json="{}",
            )
            db.add(repository); db.commit(); repository_id = repository.id
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": f"schedule-job-{suffix}", "host_id": host["id"],
                "repository_id": repository_id, "source_paths": ["/srv"],
            },
        ).json()

        created = client.post(
            "/api/schedules", headers=AUTH,
            json={
                "name": f"repository-nightly-{suffix}", "expressions": "0 2 * * *;0 14 * * *",
                "target_mode": "repository", "target_repository_id": repository_id,
                "target_host_ids": [], "target_job_ids": [], "enabled": True,
            },
        )
        jobs = client.get("/api/jobs", headers=AUTH).json()
        invalid = client.post(
            "/api/schedules", headers=AUTH,
            json={
                "name": f"invalid-target-{suffix}", "expressions": "0 3 * * *",
                "target_mode": "hosts", "target_host_ids": [99999999],
                "target_repository_id": None, "target_job_ids": [], "enabled": True,
            },
        )

    assert created.status_code == 201, created.text
    assert created.json()["assigned_job_ids"] == [job["id"]]
    listed = next(item for item in jobs if item["id"] == job["id"])
    assert listed["schedule_mode"] == "scheduled"
    assert created.json()["name"] in listed["schedule_names"]
    assert invalid.status_code == 409
    assert "Unbekannte Geräte-ID" in invalid.text


def test_dashboard_exposes_waiting_queue_count():
    marker = f"waiting-dashboard-{time.time_ns()}"
    run_id = None
    try:
        with TestClient(app) as client:
            with SessionLocal() as db:
                row = Run(action=marker, status="queued")
                db.add(row); db.commit(); run_id = row.id
            response = client.get("/api/dashboard", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["counts"]["waiting"] >= 1
    finally:
        if run_id is not None:
            with SessionLocal() as db:
                row = db.get(Run, run_id)
                if row:
                    db.delete(row); db.commit()


def test_failed_managed_repository_check_keeps_existing_repository_state(monkeypatch, tmp_path: Path):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    repository_path = tmp_path / f"managed-{suffix}"
    repository_path.mkdir()
    (repository_path / "config").write_text(
        "[repository]\nversion = 1\nid = " + ("c" * 64) + "\n",
        encoding="utf-8",
    )

    async def failed_repository_command(repository_id, command):
        return 2, "", "Failed to create/acquire the lock /repositories/.cache/borg/abc/lock.exclusive (timeout)."

    async def queued_failed_command(command, **_kwargs):
        return await failed_repository_command(None, command)

    monkeypatch.setattr(service, "execute", queued_failed_command)
    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"managed-existing-{suffix}",
                location=str(repository_path),
                storage_path=str(repository_path),
                initialized=True,
                encryption_mode="none",
                extra_env_json="{}",
            )
            db.add(repository)
            db.commit()
            repository_id = repository.id

        tested = client.post(f"/api/repositories/{repository_id}/test", headers=AUTH)
        assert tested.status_code == 202, tested.text
        run = wait_for_run_terminal(client, tested.json()["run_id"])
        deadline = time.monotonic() + 1.0
        while True:
            repositories = client.get("/api/repositories", headers=AUTH).json()
            stored = next(item for item in repositories if item["id"] == repository_id)
            if stored["validation_error"] is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.01)

    assert run["status"] == "failed"
    assert stored["initialized"] is True
    assert stored["repository_present"] is True
    assert "lokale Borg-Cache" in stored["validation_error"]


def test_repository_cache_endpoint_is_explicit_and_records_management_activity(monkeypatch, tmp_path: Path):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    repository_path = tmp_path / f"cache-{suffix}"
    repository_path.mkdir()
    (repository_path / "config").write_text(
        "[repository]\nversion = 1\nid = " + ("d" * 64) + "\n",
        encoding="utf-8",
    )

    async def cleared(repository_id):
        return {
            "repository_borg_id": "d" * 64,
            "cache_removed": True,
            "legacy_cache_removed": True,
            "removed_bytes": 4096,
        }

    monkeypatch.setattr(main_module, "clear_repository_cache", cleared)
    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"cache-endpoint-{suffix}",
                location=str(repository_path),
                storage_path=str(repository_path),
                initialized=True,
                encryption_mode="none",
                extra_env_json="{}",
            )
            db.add(repository)
            db.commit()
            repository_id = repository.id

        response = client.post(f"/api/repositories/{repository_id}/clear-cache", headers=AUTH)
        with SessionLocal() as db:
            run = db.scalar(
                select(Run).where(
                    Run.repository_id == repository_id,
                    Run.action == "repository-cache-clear",
                )
            )

    assert response.status_code == 200, response.text
    assert response.json()["legacy_cache_removed"] is True
    assert response.json()["removed_bytes"] == 4096
    assert run is not None
    assert run.status == "success"
    assert "Archive blieben unverändert" in run.output


def test_repository_cache_endpoint_rejects_queued_or_running_operations(monkeypatch, tmp_path: Path):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    repository_path = tmp_path / f"cache-active-{suffix}"
    repository_path.mkdir()
    (repository_path / "config").write_text(
        "[repository]\nversion = 1\nid = " + ("e" * 64) + "\n",
        encoding="utf-8",
    )

    called = False

    async def should_not_run(repository_id):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(main_module, "clear_repository_cache", should_not_run)
    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"cache-active-{suffix}",
                location=str(repository_path),
                storage_path=str(repository_path),
                initialized=True,
                encryption_mode="none",
                extra_env_json="{}",
            )
            db.add(repository)
            db.flush()
            run = Run(
                repository_id=repository.id,
                action="check",
                status="queued",
                command_preview="queued check",
            )
            db.add(run)
            db.commit()
            repository_id = repository.id

        response = client.post(f"/api/repositories/{repository_id}/clear-cache", headers=AUTH)

        with SessionLocal() as db:
            queued = db.get(Run, run.id)
            db.delete(queued)
            db.commit()

    assert response.status_code == 409
    assert "laufenden oder wartenden" in response.json()["detail"]
    assert called is False


def test_run_diagnosis_detects_relocated_repository_prompt():
    diagnosis = main_module.diagnose_run(
        "",
        "Warning: The repository at location ssh://new/repo was previously located at ssh://old/repo\n"
        "Do you want to continue? [yN] Aborting. Repository access aborted",
    )
    assert diagnosis["title"] == "Repository-Standort geändert"
    assert "einmalige Sicherheitsbestätigung" in diagnosis["detail"]


def test_location_confirmation_lock_diagnosis_distinguishes_external_lock():
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        repository = Repository(
            name=f"confirm-lock-{suffix}",
            location=f"/tmp/confirm-lock-{suffix}",
            extra_env_json="{}", initialized=True,
        )
        db.add(repository)
        db.flush()
        run = Run(
            repository_id=repository.id, action="confirm-location", status="failed",
            error="Failed to create/acquire the lock /repositories/borg/lock.exclusive (timeout).",
            log_output="terminating with error status, rc 2",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        result = main_module.run_json(run)

    assert result["diagnosis"]["title"] == "Repository-Sperre trotz Warteschlange nicht frei"
    assert "600 Sekunden" in result["diagnosis"]["detail"]
    assert "außerhalb" in result["diagnosis"]["action"]



def test_archive_overview_uses_persistent_cache_and_supports_explicit_refresh(monkeypatch, tmp_path):
    from uuid import uuid4
    from app import archive_cache

    suffix = uuid4().hex[:8]
    calls = []
    monkeypatch.setattr(archive_cache, "ARCHIVE_CACHE_DIR", tmp_path)

    async def listing(repository_id, command):
        calls.append((repository_id, command.preview))
        return 0, json.dumps({"archives": [
            {"name": "cached-archive", "id": "cache-1", "start": "2026-07-17T10:00:00"},
        ]}), ""

    monkeypatch.setattr(main_module, "execute_interactive", listing)
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": f"cache-host-{suffix}", "address": "10.55.0.1", "port": 22, "username": "root", "host_key": HOST_KEY},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": f"cache-repo-{suffix}", "managed": False, "location": f"/tmp/cache-{suffix}"},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={"name": f"cache-job-{suffix}", "host_id": host["id"], "repository_id": repository["id"], "source_paths": ["/srv"]},
        ).json()

        first = client.get(f"/api/jobs/{job['id']}/archives?all_archives=true", headers=AUTH)
        second = client.get(f"/api/jobs/{job['id']}/archives?all_archives=true", headers=AUTH)
        refreshed = client.get(
            f"/api/jobs/{job['id']}/archives?all_archives=true&force_refresh=true", headers=AUTH,
        )

    assert first.status_code == 200
    assert first.json()["archive_cache_source"] == "repository"
    assert second.status_code == 200
    assert second.json()["archive_cache_source"] == "cache"
    assert refreshed.status_code == 200
    assert refreshed.json()["archive_cache_source"] == "repository"
    assert len(calls) == 2



def test_archive_listing_permission_error_returns_only_actionable_cause(monkeypatch, tmp_path):
    suffix = str(time.time_ns())
    repository_path = tmp_path / "repository"
    repository_path.mkdir()
    (repository_path / "config").write_text("[repository]\nversion = 1\n", encoding="utf-8")
    with SessionLocal() as db:
        repository = Repository(
            name=f"permission-repo-{suffix}",
            location=str(repository_path),
            storage_path=str(repository_path),
            initialized=True,
        )
        db.add(repository); db.commit(); repository_id = repository.id

    error = """Exception ignored in: <function Repository.__del__ at 0x123>
Traceback (most recent call last):
  File "/usr/lib/python3/dist-packages/borg/repository.py", line 1491, in open_fd
PermissionError: [Errno 13] Permission denied: '/repositories/borg/data/69/69536'
Platform: Linux bbm
Borg: 1.4.0
"""

    async def denied(_repository_id, _command):
        return 2, "", error

    monkeypatch.setattr(main_module, "execute_interactive", denied)
    main_module.invalidate_archive_cache(repository_id)
    with TestClient(app) as client:
        response = client.get(f"/api/repositories/{repository_id}/archives?force_refresh=true", headers=AUTH)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Zugriff auf Repository-Datei verweigert" in detail
    assert "/repositories/borg/data/69/69536" in detail
    assert "Traceback" not in detail
    assert "Platform:" not in detail


def test_dashboard_jobs_include_schedule_latest_run_and_backup_sizes():
    suffix = str(time.time_ns())
    now = main_module.datetime.now(main_module.timezone.utc)
    with TestClient(app) as client:
        with SessionLocal() as db:
            host = Host(name=f"dashboard-host-{suffix}", address="127.0.0.1", username="root")
            repository = Repository(name=f"dashboard-repo-{suffix}", location=f"/tmp/dashboard-{suffix}", initialized=True)
            db.add_all([host, repository]); db.flush()
            job = Job(
                name=f"dashboard-job-{suffix}", host_id=host.id, repository_id=repository.id,
                source_paths_json='["/srv/docker", "/etc"]', exclude_patterns_json="[]",
            )
            db.add(job); db.flush()
            schedule = BackupSchedule(
                name=f"Nachtlauf-{suffix}", expressions="0 2 * * *", target_mode="jobs",
                target_job_ids_json=json.dumps([job.id]), target_host_ids_json="[]", enabled=True,
            )
            successful_run = Run(
                job_id=job.id, job_name_snapshot=job.name, repository_id=repository.id,
                action="backup", status="success", trigger_type="schedule",
                schedule_name_snapshot=schedule.name, archive_name_snapshot="bbm-1-host-2026-07-18T02:00:00",
                backup_original_size_bytes=20_000_000_000,
                backup_compressed_size_bytes=10_000_000_000,
                backup_deduplicated_size_bytes=50_000_000,
                started_at=now, finished_at=now + main_module.timedelta(seconds=125), created_at=now,
            )
            failed_run = Run(
                job_id=job.id, job_name_snapshot=job.name, repository_id=repository.id,
                action="backup", status="failed", trigger_type="manual",
                started_at=now + main_module.timedelta(minutes=10),
                finished_at=now + main_module.timedelta(minutes=10, seconds=12),
                created_at=now + main_module.timedelta(minutes=10),
            )
            db.add_all([schedule, successful_run, failed_run]); db.commit()
            job_id = job.id
            successful_run_id = successful_run.id
            failed_run_id = failed_run.id

        body = client.get("/api/dashboard", headers=AUTH).json()

    item = next(row for row in body["jobs"] if row["id"] == job_id)
    assert item["schedule_mode"] == "scheduled"
    assert item["schedule_names"] == [f"Nachtlauf-{suffix}"]
    assert item["last_run"]["id"] == failed_run_id
    assert item["last_run"]["duration_seconds"] == 12
    assert item["last_run"]["trigger_type"] == "manual"
    assert item["last_run"]["backup_deduplicated_size_bytes"] is None
    assert item["last_successful_backup"]["id"] == successful_run_id
    assert item["last_successful_backup"]["duration_seconds"] == 125
    assert item["last_successful_backup"]["trigger_type"] == "schedule"
    assert item["last_successful_backup"]["schedule_name"] == f"Nachtlauf-{suffix}"
    assert item["last_successful_backup"]["backup_deduplicated_size_bytes"] == 50_000_000


def test_repository_access_can_be_provisioned_for_one_backup_job(monkeypatch, tmp_path: Path):
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    host_key = tmp_path / "ssh_host_ed25519_key.pub"
    host_key.write_text(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEUdWrG3dnKa9pj3X6CSpTSHZ2jwzp1UgSyGgtyY+XJfHostKey manager\n",
        encoding="utf-8",
    )
    authorized_keys = tmp_path / "authorized_keys"
    monkeypatch.setattr(service, "REPOSITORY_HOST_KEY_PUBLIC_PATH", host_key)
    monkeypatch.setattr(service, "REPOSITORY_AUTHORIZED_KEYS_PATH", authorized_keys)

    selected_repository_id = 0
    other_repository_id = 0

    async def successful_bootstrap(command):
        import shlex
        remote_command = shlex.split(command.argv[-1])
        assert remote_command[-1] == str(selected_repository_id)
        assert str(other_repository_id) not in remote_command[-2:]
        return 0, (
            f"BBM_REPOSITORY_KEY {selected_repository_id} "
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISelectedDeviceKey backup@test\n"
        ), ""

    monkeypatch.setattr(service, "execute", successful_bootstrap)

    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={
                "name": f"job-access-host-{suffix}", "address": "10.0.0.88", "port": 22,
                "username": "backup", "host_key": HOST_KEY, "enabled": True,
            },
        ).json()
        with SessionLocal() as db:
            selected = Repository(
                name=f"job-access-selected-{suffix}",
                location=f"ssh://borg@manager:2222/./selected-{suffix}",
                storage_path=f"/repositories/selected-{suffix}", initialized=True,
                encryption_mode="none", extra_env_json="{}",
            )
            other = Repository(
                name=f"job-access-other-{suffix}",
                location=f"ssh://borg@manager:2222/./other-{suffix}",
                storage_path=f"/repositories/other-{suffix}", initialized=True,
                encryption_mode="none", extra_env_json="{}",
            )
            db.add_all([selected, other]); db.flush()
            selected_repository_id = selected.id
            other_repository_id = other.id
            selected_job = Job(
                name=f"job-access-selected-{suffix}", host_id=host["id"], repository_id=selected.id,
                source_paths_json='["/srv/selected"]', exclude_patterns_json="[]",
                archive_prefix=f"bbm-selected-{suffix}-", create_options_json="{}",
            )
            other_job = Job(
                name=f"job-access-other-{suffix}", host_id=host["id"], repository_id=other.id,
                source_paths_json='["/srv/other"]', exclude_patterns_json="[]",
                archive_prefix=f"bbm-other-{suffix}-", create_options_json="{}",
            )
            db.add_all([selected_job, other_job]); db.commit()
            selected_job_id = selected_job.id
        service.sync_repository_access_assignments()

        response = client.post(
            f"/api/jobs/{selected_job_id}/bootstrap-repository", headers=AUTH,
        )
        jobs = client.get("/api/jobs", headers=AUTH).json()

    assert response.status_code == 200
    assert response.json()["repository_id"] == selected_repository_id
    by_name = {item["name"]: item for item in jobs}
    assert by_name[f"job-access-selected-{suffix}"]["repository_access_ready"] is True
    assert by_name[f"job-access-other-{suffix}"]["repository_access_ready"] is False
    with SessionLocal() as db:
        selected_access = db.scalar(select(HostRepositoryAccess).where(
            HostRepositoryAccess.host_id == host["id"],
            HostRepositoryAccess.repository_id == selected_repository_id,
        ))
        other_access = db.scalar(select(HostRepositoryAccess).where(
            HostRepositoryAccess.host_id == host["id"],
            HostRepositoryAccess.repository_id == other_repository_id,
        ))
    assert selected_access and selected_access.public_key
    assert other_access and other_access.public_key is None


def test_tab_reload_token_restores_authentication_without_cookie(monkeypatch):
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    headers = {"user-agent": "BBM-Browser-Test/1.0"}
    with TestClient(app, base_url="https://testserver", headers=headers) as client:
        login = client.post("/api/auth/login", headers=BROWSER, json={"username": "admin", "password": "irrelevant"})
        assert login.status_code == 200
        reload_token = login.json()["reload_token"]
        assert reload_token
        client.cookies.clear()
        status = client.get("/api/auth/status", headers={"Authorization": f"BBM-Reload {reload_token}"})
    assert status.status_code == 200
    assert status.json()["auth_mode"] == "reload"
    assert status.json()["username"] == user.username


def test_tab_reload_token_is_bound_to_user_agent(monkeypatch):
    record = next(item for item in main_module.list_users() if item["username"] == "admin")
    user = main_module.AuthUser(
        id=record["id"], username=record["username"], role=record["role"],
        enabled=record["enabled"], must_change_password=record["must_change_password"],
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    with TestClient(app, base_url="https://testserver", headers={"user-agent": "Original-Browser"}) as client:
        login = client.post("/api/auth/login", headers=BROWSER, json={"username": "admin", "password": "irrelevant"})
        reload_token = login.json()["reload_token"]
        client.cookies.clear()
        status = client.get(
            "/api/auth/status",
            headers={"Authorization": f"BBM-Reload {reload_token}", "user-agent": "Other-Browser"},
        )
    assert status.status_code == 401


def test_frontend_uses_tab_reload_session_fallback():
    javascript = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "sessionStorage.getItem(RELOAD_SESSION_KEY)" in javascript
    assert "BBM-Reload ${token}" in javascript
    assert "storeReloadSessionToken(body.reload_token || '')" in javascript
    assert "storeReloadSessionToken('')" in javascript


def test_warning_run_exposes_concrete_borg_warning_causes():
    row = Run(
        id=12001, action="backup", status="warning", command_preview="borg create",
        output="", error="C var/lib/app/live.db\nterminating with warning status, rc 1",
        log_output="Archive name: bbm-1-host-2026-07-18T12:00:00",
    )
    payload = main_module.run_json(row)
    assert payload["warning_summary"]["changed_count"] == 1
    assert payload["warning_summary"]["items"][0]["path"] == "var/lib/app/live.db"
    assert payload["diagnosis"]["title"] == "1 Datei wurde während der Sicherung verändert"
    assert "C var/lib/app/live.db" in payload["error"]


def test_persisted_warning_summary_wins_when_bounded_logs_no_longer_contain_cause():
    row = Run(
        id=12002, action="backup", status="warning", command_preview="borg create",
        output="", error="terminating with warning status, rc 1",
        log_output="terminating with warning status, rc 1",
        warning_summary_json=json.dumps({
            "total_count": 1,
            "changed_count": 1,
            "permission_count": 0,
            "missing_count": 0,
            "io_count": 0,
            "error_count": 0,
            "other_count": 0,
            "unknown_count": 0,
            "items": [{
                "kind": "changed", "path": "var/lib/app/early.db",
                "reason": "file changed while we backed it up",
            }],
            "truncated_count": 0,
        }),
    )
    payload = main_module.run_json(row)
    assert payload["warning_summary"]["items"][0]["path"] == "var/lib/app/early.db"
    assert payload["diagnosis"]["title"] == "1 Datei wurde während der Sicherung verändert"


def test_warning_without_detail_line_is_explicitly_marked_unresolved():
    row = Run(
        id=12003, action="backup", status="warning", command_preview="borg create",
        output="", error="terminating with warning status, rc 1",
        log_output="ERGEBNIS: Backup mit Warnungen abgeschlossen.",
    )
    payload = main_module.run_json(row)
    assert payload["warning_summary"]["unresolved"] is True
    assert payload["warning_summary"]["items"][0]["kind"] == "unknown"
    assert payload["diagnosis"]["title"] == "Borg meldete eine Warnung ohne Detailzeile"


def test_running_backup_exposes_already_collected_warning_causes():
    row = Run(
        id=12004, action="backup", status="running", command_preview="borg create",
        output="", error="", log_output="backup still running",
        warning_summary_json=json.dumps({
            "total_count": 1,
            "changed_count": 1,
            "permission_count": 0,
            "missing_count": 0,
            "io_count": 0,
            "error_count": 0,
            "other_count": 0,
            "unknown_count": 0,
            "items": [{
                "kind": "changed", "path": "var/lib/app/live.db",
                "reason": "file changed while we backed it up",
            }],
            "truncated_count": 0,
        }),
    )
    payload = main_module.run_json(row)
    assert payload["warning_summary"]["items"][0]["path"] == "var/lib/app/live.db"
    assert payload["diagnosis"] is None


def test_repository_compact_queues_without_backup_job(monkeypatch):
    suffix = str(time.time_ns())
    queued = []

    def fake_queue(repository_id, action, data=None, *, subject=None, refresh_size_after=True):
        queued.append({
            "repository_id": repository_id,
            "action": action,
            "data": data,
            "subject": subject,
            "refresh_size_after": refresh_size_after,
        })
        return 901

    monkeypatch.setattr(main_module, "queue_repository_action", fake_queue)
    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"compact-repository-{suffix}",
                location=f"/tmp/compact-repository-{suffix}",
                initialized=True,
            )
            db.add(repository)
            db.commit()
            repository_id = repository.id

        response = client.post(f"/api/repositories/{repository_id}/compact", headers=AUTH)

    assert response.status_code == 202, response.text
    assert response.json() == {"run_id": 901}
    assert queued == [{
        "repository_id": repository_id,
        "action": "compact",
        "data": None,
        "subject": f"Repository: compact-repository-{suffix}",
        "refresh_size_after": True,
    }]


def test_repository_bulk_delete_resolves_multiple_devices_and_queues_once(monkeypatch):
    suffix = str(time.time_ns())
    queued = []

    def fake_queue(repository_id, action, data=None, *, subject=None, refresh_size_after=True):
        queued.append({
            "repository_id": repository_id,
            "action": action,
            "data": data,
            "subject": subject,
        })
        return 902

    monkeypatch.setattr(main_module, "queue_repository_action", fake_queue)

    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"delete-repository-{suffix}",
                location=f"/tmp/delete-repository-{suffix}",
                initialized=True,
            )
            host_a = Host(name=f"device-a-{suffix}", address="10.77.0.1", username="root")
            host_b = Host(name=f"device-b-{suffix}", address="10.77.0.2", username="root")
            db.add_all([repository, host_a, host_b])
            db.flush()
            job_a = Job(
                name=f"job-a-{suffix}", host_id=host_a.id, repository_id=repository.id,
                source_paths_json='["/srv/a"]', exclude_patterns_json="[]",
                archive_prefix=f"bbm-job-a-{suffix}-",
            )
            job_b = Job(
                name=f"job-b-{suffix}", host_id=host_b.id, repository_id=repository.id,
                source_paths_json='["/srv/b"]', exclude_patterns_json="[]",
                archive_prefix=f"bbm-job-b-{suffix}-",
            )
            db.add_all([job_a, job_b])
            db.commit()
            repository_id = repository.id
            archive_a = f"{job_a.archive_prefix}2026-07-18T10:00:00"
            archive_b = f"{job_b.archive_prefix}2026-07-18T11:00:00"

        async def listing(_repository_id, _command):
            return 0, json.dumps({"archives": [
                {"name": archive_a, "id": "a"},
                {"name": archive_b, "id": "b"},
            ]}), ""

        monkeypatch.setattr(main_module, "execute_interactive", listing)
        response = client.post(
            f"/api/repositories/{repository_id}/archive-delete",
            headers=AUTH,
            json={"archives": [archive_a, archive_b], "compact_after": True},
        )

    assert response.status_code == 202, response.text
    assert response.json()["archive_count"] == 2
    assert response.json()["device_label"] == "Mehrere Geräte"
    assert queued == [{
        "repository_id": repository_id,
        "action": "delete-archive",
        "data": {"archives": [archive_a, archive_b], "compact_after": True},
        "subject": "Mehrere Geräte",
    }]


def test_repository_bulk_delete_rejects_active_execution_before_repository_scan(monkeypatch):
    suffix = str(time.time_ns())
    scanned = False

    async def should_not_scan(_repository_id, _command):
        nonlocal scanned
        scanned = True
        return 0, '{"archives": []}', ""

    monkeypatch.setattr(main_module, "execute_interactive", should_not_scan)
    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"busy-delete-repository-{suffix}",
                location=f"/tmp/busy-delete-repository-{suffix}",
                initialized=True,
            )
            db.add(repository)
            db.flush()
            run = Run(repository_id=repository.id, action="backup", status="running")
            db.add(run)
            db.commit()
            repository_id = repository.id
            run_id = run.id

        response = client.post(
            f"/api/repositories/{repository_id}/archive-delete",
            headers=AUTH,
            json={"archives": ["archive-2026-07-18T10:00:00"], "compact_after": False},
        )

        with SessionLocal() as db:
            active = db.get(Run, run_id)
            active.status = "failed"
            db.commit()

    assert response.status_code == 409
    assert "queued or running" in response.json()["detail"]
    assert scanned is False


def test_repository_compact_creates_repository_run_without_job(monkeypatch):
    suffix = str(time.time_ns())

    async def successful_execute(_command, **_kwargs):
        return 0, "compact complete", ""

    async def no_size_refresh(_repository_id):
        return None

    monkeypatch.setattr(service, "execute", successful_execute)
    monkeypatch.setattr(service, "refresh_repository_statistics", no_size_refresh)

    with TestClient(app) as client:
        with SessionLocal() as db:
            repository = Repository(
                name=f"logged-compact-{suffix}",
                location=f"/tmp/logged-compact-{suffix}",
                initialized=True,
            )
            db.add(repository)
            db.commit()
            repository_id = repository.id

        response = client.post(f"/api/repositories/{repository_id}/compact", headers=AUTH)
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]

        for _ in range(40):
            run_response = client.get(f"/api/runs/{run_id}", headers=AUTH)
            if run_response.json()["status"] == "success":
                break
            time.sleep(0.01)

    payload = run_response.json()
    assert payload["status"] == "success"
    assert payload["job_id"] is None
    assert payload["job_name"] == f"Repository: logged-compact-{suffix}"
    with SessionLocal() as db:
        stored = db.get(Run, run_id)
        assert stored.repository_id == repository_id
    assert payload["action"] == "compact"
    assert payload["output"] == "compact complete"


def test_failed_repository_delete_invalidates_archive_cache(monkeypatch):
    suffix = str(time.time_ns())
    invalidated = []

    async def failed_execute(_command, **_kwargs):
        return 2, "first archive may already be gone", "delete failed"

    monkeypatch.setattr(service, "execute", failed_execute)
    monkeypatch.setattr(service, "invalidate_archive_cache", lambda repository_id: invalidated.append(repository_id))

    with SessionLocal() as db:
        repository = Repository(
            name=f"partial-delete-{suffix}",
            location=f"/tmp/partial-delete-{suffix}",
            initialized=True,
        )
        db.add(repository)
        db.flush()
        run = Run(
            repository_id=repository.id,
            job_id=None,
            job_name_snapshot="Mehrere Geräte",
            action="delete-archive",
            status="queued",
            command_preview="delete multiple archives",
        )
        db.add(run)
        db.commit()
        repository_id = repository.id
        run_id = run.id

    asyncio.run(service.execute_run(
        run_id,
        runner.Command(argv=["false"], preview="delete multiple archives"),
        refresh_size_after=False,
    ))

    with SessionLocal() as db:
        completed = db.get(Run, run_id)
        assert completed.status == "failed"
    assert invalidated == [repository_id]


def test_execute_run_persists_warning_cause_before_diagnostic_tail_is_truncated(monkeypatch):
    suffix = str(time.time_ns())

    async def warning_execute(_command, on_output=None, **_kwargs):
        assert on_output is not None
        await on_output("stderr", "C var/lib/app/early")
        await on_output("stderr", ".db\n")
        await on_output("stderr", "x" * (300 * 1024) + "\n")
        await on_output("stderr", "terminating with warning status, rc 1\n")
        return 1, "", "terminating with warning status, rc 1\n"

    monkeypatch.setattr(service, "execute", warning_execute)

    with SessionLocal() as db:
        repository = Repository(
            name=f"stream-warning-{suffix}",
            location=f"/tmp/stream-warning-{suffix}",
            initialized=True,
        )
        db.add(repository)
        db.flush()
        run = Run(
            repository_id=repository.id,
            job_id=None,
            job_name_snapshot="Streaming warning",
            action="backup",
            status="queued",
            command_preview="borg create",
        )
        db.add(run)
        db.commit()
        run_id = run.id

    asyncio.run(service.execute_run(
        run_id,
        runner.Command(argv=["true"], preview="borg create"),
        refresh_size_after=False,
    ))

    with SessionLocal() as db:
        completed = db.get(Run, run_id)
        assert completed.status == "warning"
        summary = json.loads(completed.warning_summary_json)
        assert summary["changed_count"] == 1
        assert summary["items"][0]["path"] == "var/lib/app/early.db"
        assert "C var/lib/app/early.db" not in (completed.error or "")


def test_deleted_empty_managed_repository_state_can_be_reset(monkeypatch, tmp_path: Path):
    from uuid import uuid4
    from app import repository_state
    from app.vault import set_repository_secret

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    root = tmp_path / "repositories"
    repository_path = root / f"reset-{suffix}"
    repository_path.mkdir(parents=True)
    monkeypatch.setattr(repository_state, "REPOSITORY_ROOT", root)

    with SessionLocal() as db:
        repository = Repository(
            name=f"reset-empty-{suffix}",
            location=f"ssh://borg@example/./reset-{suffix}",
            storage_path=str(repository_path),
            initialized=True,
            encryption_mode="keyfile-blake2",
            validation_error="old validation error",
            validation_details="old details",
            size_bytes=123,
            original_size_bytes=456,
            compressed_size_bytes=234,
            deduplicated_size_bytes=111,
            extra_env_json="{}",
        )
        db.add(repository)
        db.commit()
        repository_id = repository.id
    with TestClient(app) as client:
        set_repository_secret(repository_id, "keyfile", "old deleted repository key")
        response = client.post(f"/api/repositories/{repository_id}/reset", headers=AUTH)
        listed = client.get("/api/repositories", headers=AUTH).json()

    assert response.status_code == 200
    assert response.json()["status"] == "reset"
    assert response.json()["run_id"] > 0
    stored_out = next(item for item in listed if item["id"] == repository_id)
    assert stored_out["initialized"] is False
    assert stored_out["repository_present"] is False
    assert stored_out["validation_error"] is None
    assert stored_out["size_bytes"] is None
    assert stored_out["has_keyfile"] is False
    assert list(repository_path.iterdir()) == []

    with SessionLocal() as db:
        repository = db.get(Repository, repository_id)
        run = db.get(Run, response.json()["run_id"])
        assert repository is not None
        assert repository.initialized is False
        assert repository.validation_details is None
        assert repository.original_size_bytes is None
        assert repository.compressed_size_bytes is None
        assert repository.deduplicated_size_bytes is None
        assert run is not None
        assert run.action == "repository-reset"
        assert run.status == "success"
        assert "keine Repository-Dateien gelöscht" in (run.output or "")
    assert get_repository_secret(repository_id, "keyfile") is None


def test_repository_reset_refuses_nonempty_directory(monkeypatch, tmp_path: Path):
    from uuid import uuid4
    from app import repository_state

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    root = tmp_path / "repositories"
    repository_path = root / f"nonempty-{suffix}"
    repository_path.mkdir(parents=True)
    (repository_path / "partial-data").write_text("still here", encoding="utf-8")
    monkeypatch.setattr(repository_state, "REPOSITORY_ROOT", root)

    with SessionLocal() as db:
        repository = Repository(
            name=f"reset-nonempty-{suffix}",
            location=f"ssh://borg@example/./nonempty-{suffix}",
            storage_path=str(repository_path),
            initialized=True,
            encryption_mode="none",
            extra_env_json="{}",
        )
        db.add(repository)
        db.commit()
        repository_id = repository.id

    with TestClient(app) as client:
        response = client.post(f"/api/repositories/{repository_id}/reset", headers=AUTH)

    assert response.status_code == 400
    assert "nicht leer" in response.json()["detail"]
    assert (repository_path / "partial-data").read_text(encoding="utf-8") == "still here"
    with SessionLocal() as db:
        assert db.get(Repository, repository_id).initialized is True


def test_repository_reset_refuses_existing_borg_config(monkeypatch, tmp_path: Path):
    from uuid import uuid4
    from app import repository_state

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    root = tmp_path / "repositories"
    repository_path = root / f"present-{suffix}"
    repository_path.mkdir(parents=True)
    (repository_path / "config").write_text("[repository]\nversion = 1\n", encoding="utf-8")
    monkeypatch.setattr(repository_state, "REPOSITORY_ROOT", root)

    with SessionLocal() as db:
        repository = Repository(
            name=f"reset-present-{suffix}",
            location=f"ssh://borg@example/./present-{suffix}",
            storage_path=str(repository_path),
            initialized=True,
            encryption_mode="none",
            extra_env_json="{}",
        )
        db.add(repository)
        db.commit()
        repository_id = repository.id

    with TestClient(app) as client:
        response = client.post(f"/api/repositories/{repository_id}/reset", headers=AUTH)

    assert response.status_code == 400
    assert "weiterhin eine Borg-Konfiguration" in response.json()["detail"]
    assert (repository_path / "config").is_file()


def test_stale_initialized_repository_requires_reset_before_init(monkeypatch, tmp_path: Path):
    from uuid import uuid4
    from app import repository_state

    Base.metadata.create_all(engine)
    suffix = uuid4().hex[:8]
    root = tmp_path / "repositories"
    repository_path = root / f"stale-{suffix}"
    repository_path.mkdir(parents=True)
    monkeypatch.setattr(repository_state, "REPOSITORY_ROOT", root)

    with SessionLocal() as db:
        repository = Repository(
            name=f"stale-init-{suffix}",
            location=f"ssh://borg@example/./stale-{suffix}",
            storage_path=str(repository_path),
            initialized=True,
            encryption_mode="none",
            extra_env_json="{}",
        )
        db.add(repository)
        db.commit()
        repository_id = repository.id

    with TestClient(app) as client:
        response = client.post(f"/api/repositories/{repository_id}/init", headers=AUTH)

    assert response.status_code == 400
    assert "leere Repository" in response.json()["detail"]


def test_host_and_job_can_be_enabled_and_disabled_from_list_actions(monkeypatch):
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "toggle-host", "address": "10.0.0.61", "port": 22, "username": "backup", "host_key": HOST_KEY, "enabled": True},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "toggle-repo", "managed": False, "location": "/tmp/toggle-repo", "encryption_mode": "none", "generate_external_ssh_key": False, "scan_external_host_key": False},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": "toggle-job", "host_id": host["id"], "repository_id": repository["id"],
                "source_paths": ["/srv/data"], "exclude_patterns": [],
                "archive_template": "{hostname}-{now:%Y-%m-%dT%H:%M:%S}", "compression": "zstd,6",
                "prune_options": {}, "create_options": {}, "enabled": True,
            },
        ).json()

        disabled_host = client.post(f"/api/hosts/{host['id']}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": False})
        assert disabled_host.status_code == 200
        assert disabled_host.json()["enabled"] is False
        jobs_after_host_disable = client.get("/api/jobs", headers=AUTH).json()
        cascaded_job = next(item for item in jobs_after_host_disable if item["id"] == job["id"])
        assert cascaded_job["enabled"] is False

        enabled_host = client.post(f"/api/hosts/{host['id']}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": True})
        assert enabled_host.json()["enabled"] is True
        jobs_after_host_enable = client.get("/api/jobs", headers=AUTH).json()
        still_disabled_job = next(item for item in jobs_after_host_enable if item["id"] == job["id"])
        assert still_disabled_job["enabled"] is False

        enabled_job = client.post(f"/api/jobs/{job['id']}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": True})
        assert enabled_job.json()["enabled"] is True
        disabled_job = client.post(f"/api/jobs/{job['id']}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": False})
        assert disabled_job.status_code == 200
        assert disabled_job.json()["enabled"] is False


def test_disabling_host_cascades_to_all_related_jobs():
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "cascade-host", "address": "10.0.0.64", "port": 22, "username": "backup", "host_key": HOST_KEY, "enabled": True},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "cascade-repo", "managed": False, "location": "/tmp/cascade-repo", "encryption_mode": "none", "generate_external_ssh_key": False, "scan_external_host_key": False},
        ).json()
        job_ids = []
        for index in range(2):
            job = client.post(
                "/api/jobs", headers=AUTH,
                json={
                    "name": f"cascade-job-{index}", "host_id": host["id"], "repository_id": repository["id"],
                    "source_paths": [f"/srv/data-{index}"], "exclude_patterns": [],
                    "archive_template": "{hostname}-{now:%Y-%m-%dT%H:%M:%S}", "compression": "zstd,6",
                    "prune_options": {}, "create_options": {}, "enabled": True,
                },
            ).json()
            job_ids.append(job["id"])

        response = client.post(
            f"/api/hosts/{host['id']}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": False}
        )
        assert response.status_code == 200
        jobs = {item["id"]: item for item in client.get("/api/jobs", headers=AUTH).json()}
        assert all(jobs[job_id]["enabled"] is False for job_id in job_ids)


def test_editing_host_to_disabled_cascades_related_jobs():
    with TestClient(app) as client:
        host = client.post(
            "/api/hosts", headers=AUTH,
            json={"name": "edit-disable-host", "address": "10.0.0.63", "port": 22, "username": "backup", "host_key": HOST_KEY, "enabled": True},
        ).json()
        repository = client.post(
            "/api/repositories", headers=AUTH,
            json={"name": "edit-disable-repo", "managed": False, "location": "/tmp/edit-disable-repo", "encryption_mode": "none", "generate_external_ssh_key": False, "scan_external_host_key": False},
        ).json()
        job = client.post(
            "/api/jobs", headers=AUTH,
            json={
                "name": "edit-disable-job", "host_id": host["id"], "repository_id": repository["id"],
                "source_paths": ["/srv/data"], "exclude_patterns": [],
                "archive_template": "{hostname}-{now:%Y-%m-%dT%H:%M:%S}", "compression": "zstd,6",
                "prune_options": {}, "create_options": {}, "enabled": True,
            },
        ).json()

        response = client.put(
            f"/api/hosts/{host['id']}",
            headers={**AUTH, **BROWSER},
            json={
                "name": host["name"], "address": host["address"], "port": host["port"],
                "username": host["username"], "host_key": host["host_key"], "enabled": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        jobs = client.get("/api/jobs", headers=AUTH).json()
        assert next(item for item in jobs if item["id"] == job["id"])["enabled"] is False


def test_active_run_blocks_direct_disable_actions():
    with TestClient(app) as client:
        with SessionLocal() as db:
            host = Host(name="busy-toggle-host", address="10.0.0.62", port=22, username="backup", enabled=True, host_key=HOST_KEY)
            repository = Repository(name="busy-toggle-repo", location="/tmp/busy-toggle-repo", initialized=True)
            db.add_all([host, repository]); db.flush()
            job = Job(
                name="busy-toggle-job", host_id=host.id, repository_id=repository.id,
                source_paths_json='["/srv/data"]', exclude_patterns_json="[]",
                archive_template="{hostname}-{now:%Y-%m-%dT%H:%M:%S}", archive_prefix="bbm-9999-",
                compression="zstd,6", prune_options_json="{}", create_options_json="{}", enabled=True,
            )
            db.add(job); db.flush()
            run = Run(job_id=job.id, repository_id=repository.id, action="backup", status="running")
            db.add(run); db.commit()
            host_id, job_id = host.id, job.id
        assert client.post(f"/api/jobs/{job_id}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": False}).status_code == 409
        assert client.post(f"/api/hosts/{host_id}/enabled", headers={**AUTH, **BROWSER}, json={"enabled": False}).status_code == 409
        assert client.put(
            f"/api/hosts/{host_id}", headers={**AUTH, **BROWSER},
            json={
                "name": "busy-toggle-host", "address": "10.0.0.62", "port": 22,
                "username": "backup", "enabled": False, "host_key": HOST_KEY,
            },
        ).status_code == 409


def test_manager_backup_can_be_uploaded_as_raw_body(monkeypatch, tmp_path: Path):
    import base64
    import json
    import struct
    from app import backups as backups_module

    backup_dir = tmp_path / "backups"
    data_dir = tmp_path / "data"
    backup_dir.mkdir(); data_dir.mkdir()
    monkeypatch.setattr(main_module, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backups_module, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backups_module, "DATA_DIR", data_dir)

    name = "borgbackup-manager-backup-v1.0.42-20260719-123000-upload-api.bbm"
    header = {
        "format": backups_module.BACKUP_ENVELOPE_FORMAT,
        "format_version": 1,
        "app_version": "1.0.42",
        "created_at": "2026-07-19T12:30:00+00:00",
        "label": "upload-api",
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt-n32768-r8-p1",
        "salt": base64.b64encode(b"s" * 16).decode("ascii"),
        "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
    }
    raw_header = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = backups_module.BACKUP_MAGIC + struct.pack(">I", len(raw_header)) + raw_header + b"x" * 17

    with TestClient(app) as client:
        response = client.post(
            "/api/backups/upload",
            headers={**AUTH, **BROWSER, "X-BBM-Backup-Name": name, "Content-Type": "application/octet-stream"},
            content=payload,
        )
        duplicate = client.post(
            "/api/backups/upload",
            headers={**AUTH, **BROWSER, "X-BBM-Backup-Name": name, "Content-Type": "application/octet-stream"},
            content=payload,
        )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == name
    assert (backup_dir / name).is_file()
    assert duplicate.status_code == 409


def test_disabled_device_jobs_are_not_registered_for_active_schedules():
    from app.schedules import schedule_target_job_ids

    with TestClient(app):
        with SessionLocal() as db:
            active_host = Host(name="schedule-active-device", address="10.0.0.71", port=22, username="backup", enabled=True, host_key=HOST_KEY)
            disabled_host = Host(name="schedule-disabled-device", address="10.0.0.72", port=22, username="backup", enabled=False, host_key=HOST_KEY)
            repository = Repository(name="schedule-toggle-repo", location="/tmp/schedule-toggle-repo", initialized=True)
            db.add_all([active_host, disabled_host, repository]); db.flush()
            active_job = Job(
                name="schedule-active-job", host_id=active_host.id, repository_id=repository.id,
                source_paths_json='["/srv/active"]', exclude_patterns_json="[]",
                archive_template="{hostname}-{now:%Y-%m-%dT%H:%M:%S}", archive_prefix="bbm-9101-",
                compression="zstd,6", prune_options_json="{}", create_options_json="{}", enabled=True,
            )
            disabled_job = Job(
                name="schedule-disabled-host-job", host_id=disabled_host.id, repository_id=repository.id,
                source_paths_json='["/srv/disabled"]', exclude_patterns_json="[]",
                archive_template="{hostname}-{now:%Y-%m-%dT%H:%M:%S}", archive_prefix="bbm-9102-",
                compression="zstd,6", prune_options_json="{}", create_options_json="{}", enabled=True,
            )
            db.add_all([active_job, disabled_job]); db.flush()
            active_job_id, disabled_job_id = active_job.id, disabled_job.id
            schedule = BackupSchedule(
                name="device-enabled-filter", expressions="0 2 * * *", target_mode="hosts",
                target_host_ids_json=json.dumps([active_host.id, disabled_host.id]), enabled=True,
            )
            db.add(schedule); db.flush()
            active_ids = schedule_target_job_ids(db, schedule, enabled_jobs_only=True)
            assigned_ids = schedule_target_job_ids(db, schedule, enabled_jobs_only=False)
    assert active_ids == [active_job_id]
    assert assigned_ids == [active_job_id, disabled_job_id]


def test_notification_settings_store_secrets_without_returning_them():
    payload = {
        "enabled": True,
        "instance_name": "Test Manager",
        "language": "de",
        "events": ["backup_failed", "backup_warning"],
        "include_error_excerpt": True,
        "timeout_seconds": 8,
        "smtp_enabled": True,
        "smtp_host": "mail.example.test",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "borg",
        "smtp_password": "VerySecretSmtpPassword!",
        "smtp_clear_password": False,
        "email_from": "borg@example.test",
        "email_recipients": ["admin@example.test"],
        "webhook_enabled": True,
        "webhook_kind": "generic",
        "webhook_url": "https://hooks.example.test/bbm-secret-token",
        "webhook_clear_url": False,
        "telegram_enabled": False,
        "telegram_bot_token": None,
        "telegram_clear_token": False,
        "telegram_chat_id": "",
    }
    with TestClient(app) as client:
        response = client.put("/api/notifications/settings", headers={**AUTH, **BROWSER}, json=payload)
        loaded = client.get("/api/notifications/settings", headers=AUTH)
    assert response.status_code == 200, response.text
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["smtp_password_set"] is True
    assert body["webhook_url_set"] is True
    assert "smtp_password" not in body
    assert "webhook_url" not in body
    settings_file = TEST_DATA_DIR / "notifications.json"
    persisted = settings_file.read_text(encoding="utf-8")
    assert "VerySecretSmtpPassword" not in persisted
    assert "bbm-secret-token" not in persisted


def test_notification_test_endpoint_reports_delivery(monkeypatch):
    monkeypatch.setattr(main_module, "send_test_notification", lambda channel: [{
        "channel": channel, "status": "success", "detail": "sent",
    }])
    with TestClient(app) as client:
        response = client.post(
            "/api/notifications/test", headers={**AUTH, **BROWSER}, json={"channel": "email"},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"channel": "email", "status": "success", "detail": "sent"}


def test_source_statistics_are_persisted_from_live_scan_and_backup(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = str(time.time_ns())
    outputs = [
        (0, 'BBM_SOURCE_STATS_JSON={"size_bytes":12345,"file_count":17,"warning_count":0,"method":"python-lstat"}\n', ''),
        (0, 'Archive name: bbm-source-auto\nNumber of files: 19\nThis archive: 15.00 kB  12.00 kB  5.00 kB\n', ''),
    ]

    async def fake_execute(_command, on_output=None, **_kwargs):
        code, output, error = outputs.pop(0)
        if on_output and output:
            await on_output('stdout', output)
        return code, output, error

    monkeypatch.setattr(service, 'execute', fake_execute)
    monkeypatch.setattr(service, 'notify_run_completion', lambda _run_id: None)

    with SessionLocal() as db:
        host = Host(
            name=f'source-host-{suffix}', address='10.0.0.99', port=22,
            username='backup', host_key=HOST_KEY, enabled=True,
        )
        repository = Repository(
            name=f'source-repo-{suffix}', location=f'/tmp/source-repo-{suffix}', initialized=True,
        )
        db.add_all([host, repository])
        db.flush()
        job = Job(
            name=f'source-job-{suffix}', host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv/data"]', exclude_patterns_json='[]',
            archive_template='source-{now}', archive_prefix=f'bbm-source-{suffix}-',
            compression='zstd,6', prune_options_json='{}', create_options_json='{}', enabled=True,
        )
        db.add(job)
        db.flush()
        scan_run = Run(
            job_id=job.id, repository_id=repository.id, job_name_snapshot=job.name,
            action='source-stats', status='queued', command_preview='live scan',
        )
        db.add(scan_run)
        db.commit()
        job_id, scan_run_id = job.id, scan_run.id

    asyncio.run(service.execute_run(
        scan_run_id, runner.Command(argv=['true'], preview='live scan'), refresh_size_after=False,
    ))

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.source_size_bytes == 12345
        assert job.source_file_count == 17
        assert job.source_stats_origin == 'scan'
        backup_run = Run(
            job_id=job.id, repository_id=job.repository_id, job_name_snapshot=job.name,
            action='backup', status='queued', command_preview='borg create',
        )
        db.add(backup_run)
        db.commit()
        backup_run_id = backup_run.id

    asyncio.run(service.execute_run(
        backup_run_id, runner.Command(argv=['true'], preview='borg create'), refresh_size_after=False,
    ))

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        run = db.get(Run, backup_run_id)
        assert job.source_size_bytes == 15000
        assert job.source_file_count == 19
        assert job.source_stats_origin == 'backup'
        assert run.backup_file_count == 19


def test_editing_job_source_configuration_clears_stale_source_statistics():
    from app.schemas import DEFAULT_CREATE_OPTIONS, JobIn

    row = Job(
        id=999001, name='source-config', host_id=1, repository_id=2,
        source_paths_json='["/srv/data"]', exclude_patterns_json='["*/cache"]',
        archive_template='source-{now}', compression='zstd,6', prune_options_json='{}',
        create_options_json=json.dumps(DEFAULT_CREATE_OPTIONS), enabled=True,
        source_size_bytes=1000, source_file_count=10, source_stats_origin='backup',
    )
    unchanged = JobIn(
        name='source-config', host_id=1, repository_id=2, source_paths=['/srv/data'],
        exclude_patterns=['*/cache'], archive_template='source-{now}', compression='zstd,6',
        prune_options={}, create_options=dict(DEFAULT_CREATE_OPTIONS), enabled=True,
    )
    main_module.apply_job(row, unchanged)
    assert row.source_size_bytes == 1000
    assert row.source_file_count == 10

    changed = unchanged.model_copy(update={'source_paths': ['/srv/data', '/etc']})
    main_module.apply_job(row, changed)
    assert row.source_size_bytes is None
    assert row.source_file_count is None
    assert row.source_stats_checked_at is None
    assert row.source_stats_origin is None


def test_run_json_can_limit_active_live_log_window(monkeypatch):
    requested_limits = []

    def fake_read_run_log(_run_id, max_bytes):
        requested_limits.append(max_bytes)
        return "live output"

    monkeypatch.setattr(main_module, "read_run_log", fake_read_run_log)
    row = Run(id=10001, action="backup", status="running", log_output="preview")
    payload = main_module.run_json(row, log_max_bytes=256 * 1024)

    assert requested_limits == [256 * 1024]
    assert payload["log_output"] == "live output"


def test_run_json_uses_offset_based_live_delta(monkeypatch):
    requested = []

    def fake_delta(run_id, offset, max_bytes):
        requested.append((run_id, offset, max_bytes))
        return {"text": "new lines\n", "offset": 1234, "reset": False, "truncated": False}

    monkeypatch.setattr(main_module, "read_run_log_delta", fake_delta)
    monkeypatch.setattr(main_module, "run_log_path", lambda _run_id: Path("/tmp/does-not-exist"))
    row = Run(id=10002, action="backup", status="running", log_output="old preview")
    payload = main_module.run_json(row, log_max_bytes=256 * 1024, log_offset=999)

    assert requested == [(10002, 999, 256 * 1024)]
    assert payload["log_output"] == "new lines\n"
    assert payload["log_offset"] == 1234
    assert payload["log_reset"] is False


def test_execute_run_keeps_raw_file_list_out_of_sqlite_previews(monkeypatch):
    suffix = str(time.time_ns())
    raw_error = (
        "A srv/data/one.txt\n"
        "M srv/data/two.txt\n"
        "C var/lib/app/live.db\n"
        "terminating with warning status, rc 1\n"
    )

    async def warning_execute(_command, on_output_bytes=None, **_kwargs):
        assert on_output_bytes is not None
        await on_output_bytes("stdout", b"BACKUP-JOB: database-preview\n")
        await on_output_bytes("stderr", raw_error.encode())
        return 1, "BACKUP-JOB: database-preview\n", raw_error

    monkeypatch.setattr(service, "execute", warning_execute)

    with SessionLocal() as db:
        repository = Repository(
            name=f"db-preview-{suffix}", location=f"/tmp/db-preview-{suffix}", initialized=True,
        )
        db.add(repository)
        db.flush()
        run = Run(
            repository_id=repository.id, job_id=None, job_name_snapshot="Database preview",
            action="backup", status="queued", command_preview="borg create",
        )
        db.add(run)
        db.commit()
        run_id = run.id

    asyncio.run(service.execute_run(
        run_id, runner.Command(argv=["true"], preview="borg create"), refresh_size_after=False,
    ))

    with SessionLocal() as db:
        completed = db.get(Run, run_id)
        assert completed.status == "warning"
        assert "srv/data/one.txt" not in completed.output
        assert "srv/data/one.txt" not in completed.error
        assert "srv/data/one.txt" not in completed.log_output
        assert "srv/data/two.txt" not in completed.log_output
        assert "var/lib/app/live.db" not in completed.error
        assert "var/lib/app/live.db" not in completed.log_output
        assert "var/lib/app/live.db" in completed.warning_summary_json
