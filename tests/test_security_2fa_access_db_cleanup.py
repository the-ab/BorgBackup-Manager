from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import security_store
from app.access_logging import write_access_event
from app.backups import cleanup_stale_security_snapshots
from app.config import ACCESS_LOG_PATH, DATA_DIR
from app.database import SessionLocal, engine
from app.database_maintenance import cleanup_manager_database, database_cleanup_preview
from app.sqlite_maintenance import MANAGER_VACUUM_PENDING_PATH
from app.main import app
from app.models import Run
from app.schemas import ManagerBackupRestoreIn
from app.two_factor import totp_code
from tests.auth_helpers import TEST_ADMIN_PASSWORD, admin_headers

BROWSER = {"X-BBM-Request": "1"}


def _admin_record() -> dict:
    security_store.initialize_security_store()
    admin = next(item for item in security_store.list_users() if item["role"] == "admin")
    security_store.set_user_password(int(admin["id"]), TEST_ADMIN_PASSWORD, must_change_password=False)
    security_store.reset_two_factor(int(admin["id"]))
    return admin


def test_totp_two_factor_login_and_recovery_code():
    admin = _admin_record()
    headers = admin_headers()
    with TestClient(app, base_url="https://testserver", headers=headers) as client:
        setup = client.post("/api/auth/2fa/setup", json={"current_password": TEST_ADMIN_PASSWORD})
        assert setup.status_code == 200
        body = setup.json()
        assert body["provisioning_uri"].startswith("otpauth://totp/")
        assert body["qr_code_data_uri"].startswith("data:image/svg+xml;base64,")
        qr_svg = base64.b64decode(body["qr_code_data_uri"].split(",", 1)[1]).decode("utf-8")
        assert "<svg" in qr_svg
        assert "otpauth://" not in qr_svg
        assert len(body["recovery_codes"]) == 10

        confirm = client.post("/api/auth/2fa/confirm", json={"code": totp_code(body["secret"])})
        assert confirm.status_code == 200

    with TestClient(app, base_url="https://testserver") as client:
        challenge = client.post("/api/auth/login", headers=BROWSER, json={
            "username": admin["username"], "password": TEST_ADMIN_PASSWORD,
        })
        assert challenge.status_code == 202
        assert challenge.json()["status"] == "two-factor-required"

        login = client.post("/api/auth/login", headers=BROWSER, json={
            "username": admin["username"], "password": TEST_ADMIN_PASSWORD,
            "second_factor": totp_code(body["secret"]),
        })
        assert login.status_code == 200
        assert login.json()["two_factor_enabled"] is True

    with TestClient(app, base_url="https://testserver") as client:
        recovery = client.post("/api/auth/login", headers=BROWSER, json={
            "username": admin["username"], "password": TEST_ADMIN_PASSWORD,
            "second_factor": body["recovery_codes"][0],
        })
        assert recovery.status_code == 200
        assert recovery.json()["recovery_code_used"] is True
        reused = client.post("/api/auth/login", headers=BROWSER, json={
            "username": admin["username"], "password": TEST_ADMIN_PASSWORD,
            "second_factor": body["recovery_codes"][0],
        })
        assert reused.status_code == 401
    security_store.reset_two_factor(int(admin["id"]))


def test_access_log_is_json_lines_and_never_contains_credentials():
    ACCESS_LOG_PATH.unlink(missing_ok=True)
    write_access_event(
        "login_failed", remote_address="192.0.2.44", username="admin",
        status="failed", detail="invalid_credentials", user_agent="pytest",
    )
    payload = json.loads(ACCESS_LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["event"] == "login_failed"
    assert payload["remote_address"] == "192.0.2.44"
    assert payload["detail"] == "invalid_credentials"
    assert "password" not in payload
    assert "second_factor" not in payload


def test_stale_security_snapshot_family_is_removed():
    paths = [
        DATA_DIR / "bbm-security-test.sqlite3",
        DATA_DIR / "bbm-security-test.sqlite3-wal",
        DATA_DIR / "bbm-security-test.sqlite3-shm",
    ]
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    for path in paths:
        path.write_bytes(b"temporary")
        os.utime(path, (old, old))
    assert cleanup_stale_security_snapshots(older_than_seconds=60) == 3
    assert not any(path.exists() for path in paths)



def test_fresh_orphan_security_sidecars_are_removed_immediately():
    paths = [
        DATA_DIR / "bbm-security-orphan.sqlite3-wal",
        DATA_DIR / "bbm-security-orphan.sqlite3-shm",
    ]
    for path in paths:
        path.write_bytes(b"temporary")
    assert cleanup_stale_security_snapshots(older_than_seconds=3600) == 2
    assert not any(path.exists() for path in paths)


def test_existing_two_factor_setup_cannot_be_replaced_without_disable():
    admin = _admin_record()
    setup = security_store.begin_two_factor_setup(int(admin["id"]), TEST_ADMIN_PASSWORD)
    security_store.confirm_two_factor_setup(int(admin["id"]), totp_code(setup["secret"]))
    try:
        try:
            security_store.begin_two_factor_setup(int(admin["id"]), TEST_ADMIN_PASSWORD)
        except ValueError as exc:
            assert "bereits aktiviert" in str(exc)
        else:
            raise AssertionError("enabled 2FA setup was unexpectedly replaced")
    finally:
        security_store.reset_two_factor(int(admin["id"]))


def test_manager_database_cleanup_repairs_only_stale_or_orphaned_rows():
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with SessionLocal() as db:
        run = Run(action="backup", status="running", command_preview="", created_at=old)
        db.add(run)
        db.commit()
        run_id = run.id
    # Simulate a legacy orphan created before foreign-key enforcement was
    # enabled on every manager.db connection.
    database_path = Path(engine.url.database)
    import sqlite3
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO host_repository_access(host_id,repository_id,public_key,created_at,updated_at) "
            "VALUES(999991,999992,NULL,?,?)",
            (old.isoformat(), old.isoformat()),
        )
        connection.commit()
    preview = database_cleanup_preview()
    assert preview["stale_active_runs"] >= 1
    assert preview["orphan_repository_access_rows"] >= 1

    result = cleanup_manager_database(create_safety_copy=True, vacuum=False)
    assert result["counts"]["stale_runs_closed"] >= 1
    assert result["counts"]["orphan_repository_access_rows_removed"] >= 1
    assert Path(result["safety_copy"]).is_file()
    with SessionLocal() as db:
        stored = db.get(Run, run_id)
        assert stored is not None
        assert stored.status == "failed"



def test_database_cleanup_defers_exclusive_vacuum_until_restart():
    MANAGER_VACUUM_PENDING_PATH.unlink(missing_ok=True)
    result = cleanup_manager_database(create_safety_copy=False, vacuum=True)
    try:
        assert result["vacuumed"] is False
        assert result["vacuum_deferred"] is True
        assert result["restart_required"] is True
        assert MANAGER_VACUUM_PENDING_PATH.is_file()
        source = Path("app/database_maintenance.py").read_text(encoding="utf-8")
        assert 'connection.exec_driver_sql("VACUUM")' not in source
    finally:
        MANAGER_VACUUM_PENDING_PATH.unlink(missing_ok=True)

def test_restore_uses_one_passphrase_and_backup_cards_are_compact():
    model = ManagerBackupRestoreIn(passphrase="Restore-Passphrase-2026!", confirm=True)
    assert model.passphrase.get_secret_value() == "Restore-Passphrase-2026!"
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    css = Path("app/static/style.css").read_text(encoding="utf-8")
    assert "safety_passphrase" not in html
    assert "safety_passphrase_confirm" not in html
    assert "compact-backup-panel" in html
    assert "regenerate-two-factor-codes" in html
    assert "BBM_ACCESS_LOG_PATH" in Path("compose.yaml").read_text(encoding="utf-8")
    assert ".backup-manager-grid .backup-restore-panel { grid-column: auto; }" in css


def test_two_factor_ui_shows_local_qr_and_labeled_recovery_codes():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    javascript = Path("app/static/app.js").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert 'id="two-factor-qr-code"' in html
    assert "Der QR-Code wird lokal von BorgBackup Manager erzeugt" in html
    assert '<h3 id="two-factor-recovery-heading">Wiederherstellungscodes</h3>' in html
    assert 'aria-label="Wiederherstellungscodes"' in html
    assert 'id="copy-two-factor-recovery-codes"' in html
    assert "result.qr_code_data_uri" in javascript
    assert "qrcode==8.2" in requirements


def test_profile_page_and_backup_upload_layout_are_compact():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    javascript = Path("app/static/app.js").read_text(encoding="utf-8")
    css = Path("app/static/style.css").read_text(encoding="utf-8")
    assert 'data-view="profile" id="profile-settings"' in html
    assert 'id="view-profile"' in html
    assert 'id="profile-preferences-form"' in html
    assert 'id="profile-password-form"' in html
    assert 'id="profile-dialog"' not in html
    assert 'class="aside-account"' in html
    assert '.aside-account {' in css
    assert "if (view === 'profile') loadProfilePage()" in javascript
    assert 'id="user-preferences"' not in html
    assert 'id="change-password"' not in html
    assert 'id="two-factor-settings"' not in html
    manager_start = html.index('id="backup-form"')
    manager_end = html.index('</form>', manager_start)
    upload_start = html.index('id="backup-upload-form"')
    cache_start = html.index('id="cache-backup-form"')
    assert manager_start < manager_end < upload_start < cache_start
    assert '<div class="backup-manager-column">' in html
