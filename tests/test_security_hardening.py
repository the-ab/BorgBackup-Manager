from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main_module
from app import backups, request_security, secret_crypto, security_bootstrap, security_store
from app.main import app
from app.schemas import RepositoryIn

BROWSER = {"X-BBM-Request": "1"}


def _isolated_security_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    security_dir = tmp_path / "security"
    database = security_dir / "security.db"
    monkeypatch.setattr(security_store, "SECURITY_DIR", security_dir)
    monkeypatch.setattr(security_store, "SECURITY_DATABASE_PATH", database)
    monkeypatch.setattr(security_store, "INITIAL_ADMIN_PATH", security_dir / "initial-admin.txt")
    monkeypatch.setattr(secret_crypto, "MASTER_KEY_PATH", security_dir / "master.key")
    security_store.initialize_security_store("Security-Test-Password-2026!")
    return database


def test_unsafe_browser_api_requires_csrf_header_and_matching_origin(monkeypatch):
    user = main_module.AuthUser(
        id=1, username="admin", role="admin", enabled=True, must_change_password=False,
    )
    monkeypatch.setattr(main_module, "authenticate_user", lambda *_args, **_kwargs: user)
    with TestClient(app, base_url="https://testserver") as client:
        missing = client.post("/api/auth/login", json={"username": "admin", "password": "irrelevant"})
        wrong_origin = client.post(
            "/api/auth/login",
            headers={**BROWSER, "Origin": "https://attacker.example"},
            json={"username": "admin", "password": "irrelevant"},
        )
        valid = client.post(
            "/api/auth/login",
            headers={**BROWSER, "Origin": "https://testserver"},
            json={"username": "admin", "password": "irrelevant"},
        )
    assert missing.status_code == 403
    assert wrong_origin.status_code == 403
    assert valid.status_code == 200


def test_login_rate_limit_is_source_scoped_and_does_not_lock_account(monkeypatch, tmp_path: Path):
    _isolated_security_store(monkeypatch, tmp_path)
    monkeypatch.setattr(security_store, "LOGIN_RATE_MAX_PER_IP", 2)
    monkeypatch.setattr(security_store, "LOGIN_RATE_MAX_PER_IP_USER", 2)
    monkeypatch.setattr(security_store, "LOGIN_RATE_BLOCK_SECONDS", 120)

    assert security_store.consume_login_attempt("admin", "192.0.2.10") == (True, 0)
    assert security_store.consume_login_attempt("admin", "192.0.2.10") == (True, 0)
    allowed, retry_after = security_store.consume_login_attempt("admin", "192.0.2.10")
    assert allowed is False and retry_after > 0
    assert security_store.consume_login_attempt("admin", "192.0.2.11") == (True, 0)
    assert security_store.authenticate_user("admin", "Security-Test-Password-2026!", "192.0.2.11") is not None
    assert security_store.authentication_readiness()["locked_administrators"] == 0


def test_session_idle_timeout_revokes_stale_session(monkeypatch, tmp_path: Path):
    database = _isolated_security_store(monkeypatch, tmp_path)
    monkeypatch.setattr(security_store, "SESSION_IDLE_TIMEOUT_SECONDS", 60)
    user = security_store.authenticate_user("admin", "Security-Test-Password-2026!")
    assert user is not None
    token = security_store.create_session(user, 3600)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sessions SET last_seen_at=?", (stale,))
        connection.commit()
    assert security_store.get_session_user(token) is None


def test_restore_permissions_manifest_cannot_escape_staging(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.write_text("unchanged", encoding="utf-8")
    os.chmod(victim, 0o600)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": backups.BACKUP_FORMAT}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"sqlite-placeholder")
        archive.writestr("permissions.json", json.dumps({"../victim": 0o777}))
    archive_bytes.seek(0)
    with zipfile.ZipFile(archive_bytes) as archive:
        with pytest.raises(ValueError, match="Unsicherer Backup-Pfad"):
            backups._safe_extract(archive, staging)
    assert stat.S_IMODE(victim.stat().st_mode) == 0o600
    assert victim.read_text(encoding="utf-8") == "unchanged"


def test_restore_rejects_archives_exceeding_entry_limit(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backups, "BACKUP_MAX_ENTRIES", 2)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": backups.BACKUP_FORMAT}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"db")
    archive_bytes.seek(0)
    with zipfile.ZipFile(archive_bytes) as archive:
        with pytest.raises(ValueError, match="mehr als 2 Einträge"):
            backups._safe_extract(archive, staging)


def test_new_manager_backups_require_strong_encryption(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backups, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backups, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError, match="verschlüsselt"):
        backups.create_full_backup("1.0.38", "insecure", None)
    with pytest.raises(ValueError, match="mindestens 12"):
        backups._encrypt_backup(tmp_path / "missing.zip", tmp_path / "out.bbm", {}, "too-short")


def test_process_control_environment_variables_are_rejected():
    with pytest.raises(ValidationError, match="reserved Borg environment variables"):
        RepositoryIn(
            name="unsafe-env", managed=False, location="ssh://backup@example/./repo",
            encryption_mode="repokey", extra_env={"LD_PRELOAD": "/tmp/evil.so"},
        )


def test_container_and_dependency_hardening_is_present():
    root = Path(__file__).parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    sshd = (root / "docker" / "sshd_config").read_text(encoding="utf-8")
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:3.13.14-slim-trixie@sha256:6771159")
    assert "fastapi==0.139.2" in requirements
    assert "starlette==1.3.1" in requirements
    assert "--hash=sha256:" in requirements
    assert "--require-hashes" in dockerfile
    assert "runuser -u borg -- env HOME=/repositories" in entrypoint
    assert "--no-proxy-headers" in entrypoint
    assert "StrictModes yes" in sshd
    assert "no-new-privileges:true" in compose


def test_public_health_hides_components_and_admin_route_exposes_them(monkeypatch, tmp_path: Path):
    database = _isolated_security_store(monkeypatch, tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
        connection.commit()
    monkeypatch.setattr(main_module, "repository_sshd_listening", lambda: False)
    monkeypatch.setattr(main_module, "HEALTH_REQUIRE_SSHD", True)
    with TestClient(app, base_url="https://testserver") as client:
        public = client.get("/api/health")
        strict = client.get("/api/health/strict")
        denied = client.get("/api/system/health")
        login = client.post(
            "/api/auth/login", headers=BROWSER,
            json={"username": "admin", "password": "Security-Test-Password-2026!"},
        )
        assert login.status_code == 200, login.text
        detailed = client.get("/api/system/health")
    assert public.json() == {"status": "degraded"}
    assert strict.status_code == 503 and strict.json() == {"status": "degraded"}
    assert denied.status_code == 401
    assert detailed.status_code == 503
    assert detailed.json()["repository_sshd"] is False


def test_viewer_ui_hides_backup_data_and_operational_controls():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert '<button data-admin-only="" data-view="archives">' in html
    assert '<button data-admin-only="" data-view="restore">' in html
    assert "'archives', 'restore'" in javascript
    assert "Nur Ansicht" in javascript
    for route in (
        '@app.post("/api/jobs/{job_id}/actions/{action}", status_code=202, dependencies=admin_protected)',
        '@app.post("/api/jobs/{job_id}/restore", status_code=202, dependencies=admin_protected)',
        '@app.get("/api/repositories/{repository_id}/archives", dependencies=admin_protected)',
        '@app.get("/api/runs/{run_id}", dependencies=admin_protected)',
        '@app.post("/api/runs/{run_id}/cancel", status_code=202, dependencies=admin_protected)',
    ):
        assert route in main



def test_restore_rejects_single_entry_with_extreme_compression(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backups, "BACKUP_MAX_COMPRESSION_RATIO", 2)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": backups.BACKUP_FORMAT}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"0" * 4096)
    archive_bytes.seek(0)
    with zipfile.ZipFile(archive_bytes) as archive:
        with pytest.raises(ValueError, match="Backup-Eintrag"):
            backups._safe_extract(archive, staging)


def test_restore_rejects_out_of_range_permission_modes(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": backups.BACKUP_FORMAT}))
        archive.writestr("migration.env", "TZ=Europe/Berlin\n")
        archive.writestr("data/manager.db", b"db")
        archive.writestr("permissions.json", json.dumps({"data/manager.db": 0o10000}))
    archive_bytes.seek(0)
    with zipfile.ZipFile(archive_bytes) as archive:
        with pytest.raises(ValueError, match="Berechtigungsmanifest enthält ungültige Werte"):
            backups._safe_extract(archive, staging)


def test_browser_origin_rejects_whitespace_in_host_header():
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", b"test server")],
        "client": ("192.0.2.44", 12345),
        "server": ("testserver", 443),
    })
    assert request_security.browser_origin(request) == ""


def test_unprivileged_runtime_bootstrap_preserves_root_owned_host_key(monkeypatch, tmp_path: Path):
    runtime_root = tmp_path / "bbm-secrets"
    private_key = runtime_root / "repository-ssh" / "ssh_host_ed25519_key"
    private_key.parent.mkdir(parents=True)
    private_key.write_text("root-prepared-private-key\n", encoding="utf-8")
    os.chmod(private_key, 0o600)

    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):
        if path == private_key:
            raise PermissionError(1, "Operation not permitted", str(path))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(security_bootstrap.os, "geteuid", lambda: 1000)

    security_bootstrap._write_runtime(
        private_key,
        "replacement-must-not-be-written\n",
        0o600,
        allow_prepared_root_private=True,
    )

    assert original_read_text(private_key, encoding="utf-8") == "root-prepared-private-key\n"
    assert stat.S_IMODE(private_key.stat().st_mode) == 0o600


def test_unprivileged_runtime_bootstrap_does_not_chmod_root_directory(monkeypatch, tmp_path: Path):
    runtime_root = tmp_path / "bbm-secrets"
    runtime_root.mkdir()
    os.chmod(runtime_root, 0o750)
    chmod_calls: list[tuple[Path, int]] = []

    monkeypatch.setattr(security_bootstrap.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        security_bootstrap.os,
        "chmod",
        lambda path, mode: chmod_calls.append((Path(path), mode)),
    )

    security_bootstrap._chmod_if_owned(runtime_root, 0o700)

    assert chmod_calls == []
    assert stat.S_IMODE(runtime_root.stat().st_mode) == 0o750


def test_entrypoint_records_root_sshd_validation_for_unprivileged_diagnostics():
    root = Path(__file__).parents[1]
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")

    validate_pos = entrypoint.index("/usr/sbin/sshd -t")
    marker_pos = entrypoint.index("printf 'ok\\n' > /run/bbm-secrets/sshd-config.valid")
    api_pos = entrypoint.index("runuser -u borg -- env HOME=/repositories")
    assert validate_pos < marker_pos < api_pos
    assert 'RUNTIME_SECRET_DIR / "sshd-config.valid"' in main
    assert 'manager_borg_argv(parts)' in main


def test_entrypoint_marks_runtime_security_as_prepared_before_unprivileged_api_start():
    root = Path(__file__).parents[1]
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")

    bootstrap_pos = entrypoint.index("python -m app.security_bootstrap")
    marker_pos = entrypoint.index("export BBM_RUNTIME_SECURITY_PREPARED=1")
    api_pos = entrypoint.index("runuser -u borg -- env HOME=/repositories")
    assert bootstrap_pos < marker_pos < api_pos
    assert 'if os.getenv("BBM_RUNTIME_SECURITY_PREPARED") != "1":' in main
