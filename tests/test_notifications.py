from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Host, Job, NotificationDelivery, Repository, Run
from app import notifications


def _reset_notification_state() -> None:
    notifications.NOTIFICATION_SETTINGS_PATH.unlink(missing_ok=True)
    notifications.HEALTH_NOTIFICATION_STATE_PATH.unlink(missing_ok=True)
    from app.security_store import delete_secret, initialize_security_store
    initialize_security_store()
    for name in (
        notifications.SMTP_PASSWORD_SECRET,
        notifications.WEBHOOK_URL_SECRET,
        notifications.TELEGRAM_TOKEN_SECRET,
    ):
        delete_secret("system", name)
    with SessionLocal() as db:
        db.query(NotificationDelivery).delete()
        db.commit()


def test_failed_backup_is_dispatched_to_generic_webhook(monkeypatch):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        events=["backup_failed"],
        webhook_enabled=True,
        webhook_kind="generic",
        webhook_url="https://hooks.example.test/secret",
    ))
    captured = {}
    monkeypatch.setattr(notifications, "_post_json", lambda url, payload, timeout: captured.update(
        url=url, payload=payload, timeout=timeout,
    ))
    with SessionLocal() as db:
        suffix = uuid.uuid4().hex[:10]
        host = Host(name=f"notify-host-{suffix}", address="127.0.0.1", username="root")
        repository = Repository(name=f"notify-repo-{suffix}", location=f"/tmp/notify-{suffix}", initialized=True)
        db.add_all([host, repository]); db.flush()
        job = Job(name=f"notify-job-{suffix}", host_id=host.id, repository_id=repository.id)
        db.add(job); db.flush()
        run = Run(
            job_id=job.id, repository_id=repository.id, job_name_snapshot=job.name,
            action="backup", status="failed", error="Connection refused",
            started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
        )
        db.add(run); db.commit(); run_id = run.id

    results = notifications.notify_run_completion(run_id)
    assert results == [{"channel": "webhook", "status": "success", "detail": "Benachrichtigung erfolgreich versendet"}]
    assert captured["url"] == "https://hooks.example.test/secret"
    assert captured["payload"]["event"] == "backup_failed"
    assert captured["payload"]["run_id"] == run_id
    assert "Connection refused" in captured["payload"]["message"]
    with SessionLocal() as db:
        delivery = db.scalar(select(NotificationDelivery).where(NotificationDelivery.run_id == run_id))
        assert delivery is not None
        assert delivery.status == "success"


def test_delivery_failure_is_recorded_and_does_not_raise(monkeypatch):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        events=["backup_warning"],
        webhook_enabled=True,
        webhook_url="https://hooks.example.test/secret-token",
    ))
    monkeypatch.setattr(notifications, "_post_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret-token failed")))
    with SessionLocal() as db:
        run = Run(
            job_name_snapshot="warning job", action="backup", status="warning",
            warning_summary_json=json.dumps({"total_count": 1, "items": [{"kind": "changed", "path": "/srv/file", "reason": "changed during backup"}]}),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run); db.commit(); run_id = run.id
    results = notifications.notify_run_completion(run_id)
    assert results[0]["status"] == "failed"
    assert "secret-token" not in results[0]["detail"]
    with SessionLocal() as db:
        delivery = db.scalar(select(NotificationDelivery).where(NotificationDelivery.run_id == run_id))
        assert delivery is not None and delivery.status == "failed"
        assert "secret-token" not in delivery.detail


def test_disabled_notification_center_does_not_contact_channels(monkeypatch):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    called = []
    monkeypatch.setattr(notifications, "_send_webhook", lambda *_args: called.append(True))
    with SessionLocal() as db:
        run = Run(action="backup", status="failed", finished_at=datetime.now(timezone.utc))
        db.add(run); db.commit(); run_id = run.id
    assert notifications.notify_run_completion(run_id) == []
    assert called == []


def test_warning_notification_includes_affected_paths_in_german_message():
    Base.metadata.create_all(engine)
    _reset_notification_state()
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        language="de",
        events=["backup_warning"],
    ))
    with SessionLocal() as db:
        run = Run(
            job_name_snapshot="Warnungsjob",
            action="backup",
            status="warning",
            warning_summary_json=json.dumps({
                "total_count": 2,
                "items": [
                    {"kind": "changed", "path": "/srv/data/live.db", "reason": "file changed while we backed it up"},
                    {"kind": "changed", "path": "/srv/data/cache.db", "reason": "file changed while we backed it up"},
                ],
            }),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run); db.commit(); run_id = run.id

    message = notifications.build_run_message(run_id)
    assert message is not None
    assert "Warnungsursachen:" in message.body
    assert "changed – file changed while we backed it up" in message.body
    assert "Betroffene Datei/Pfad: /srv/data/live.db" in message.body
    assert "Betroffene Datei/Pfad: /srv/data/cache.db" in message.body


def test_warning_notification_includes_affected_path_in_english_message():
    Base.metadata.create_all(engine)
    _reset_notification_state()
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        language="en",
        events=["backup_warning"],
    ))
    with SessionLocal() as db:
        run = Run(
            job_name_snapshot="Warning job",
            action="backup",
            status="warning",
            warning_summary_json=json.dumps({
                "total_count": 1,
                "items": [{"kind": "changed", "path": "/srv/data/live.db", "reason": "file changed while we backed it up"}],
            }),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(run); db.commit(); run_id = run.id

    message = notifications.build_run_message(run_id)
    assert message is not None
    assert "Warnings:" in message.body
    assert "Affected file/path: /srv/data/live.db" in message.body


def test_system_health_notifications_are_transition_based(monkeypatch, tmp_path):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    state_path = tmp_path / "health-state.json"
    monkeypatch.setattr(notifications, "HEALTH_NOTIFICATION_STATE_PATH", state_path)
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        system_health_notifications=True,
        webhook_enabled=True,
        webhook_url="https://hooks.example.test/health-secret",
    ))
    sent = []
    monkeypatch.setattr(notifications, "_post_json", lambda url, payload, timeout: sent.append(payload))
    degraded = {
        "status": "degraded", "database": True, "authentication": True,
        "scheduler": True, "repository_sshd": False,
    }
    healthy = {
        "status": "ok", "database": True, "authentication": True,
        "scheduler": True, "repository_sshd": True,
    }

    assert notifications.notify_system_health_observation(degraded, confirmations=2) == []
    second = notifications.notify_system_health_observation(degraded, confirmations=2)
    assert second and second[0]["status"] == "success"
    assert sent[-1]["event"] == "system_health_degraded"
    assert notifications.notify_system_health_observation(degraded, confirmations=2) == []

    assert notifications.notify_system_health_observation(healthy, confirmations=2) == []
    recovered = notifications.notify_system_health_observation(healthy, confirmations=2)
    assert recovered and recovered[0]["status"] == "success"
    assert sent[-1]["event"] == "system_health_restored"
    assert notifications.notify_system_health_observation(healthy, confirmations=2) == []


def test_system_health_notification_can_send_when_delivery_log_database_fails(monkeypatch, tmp_path):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    monkeypatch.setattr(notifications, "HEALTH_NOTIFICATION_STATE_PATH", tmp_path / "health-state.json")
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        system_health_notifications=True,
        webhook_enabled=True,
        webhook_url="https://hooks.example.test/health-secret",
    ))
    sent = []
    monkeypatch.setattr(notifications, "_post_json", lambda url, payload, timeout: sent.append(payload))
    monkeypatch.setattr(notifications, "_record_delivery", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")))
    degraded = {
        "status": "degraded", "database": False, "authentication": True,
        "scheduler": True, "repository_sshd": True,
    }
    results = notifications.notify_system_health_observation(degraded, confirmations=1)
    assert results == [{"channel": "webhook", "status": "success", "detail": "Benachrichtigung erfolgreich versendet"}]
    assert sent and sent[-1]["event"] == "system_health_degraded"


def test_system_health_notifications_can_be_disabled_independently(monkeypatch, tmp_path):
    Base.metadata.create_all(engine)
    _reset_notification_state()
    monkeypatch.setattr(notifications, "HEALTH_NOTIFICATION_STATE_PATH", tmp_path / "health-state.json")
    notifications.save_notification_settings(notifications.NotificationSettingsInput(
        enabled=True,
        system_health_notifications=False,
        webhook_enabled=True,
        webhook_url="https://hooks.example.test/health-secret",
    ))
    called = []
    monkeypatch.setattr(notifications, "_post_json", lambda *_args, **_kwargs: called.append(True))
    degraded = {
        "status": "degraded", "database": True, "authentication": True,
        "scheduler": False, "repository_sshd": True,
    }
    assert notifications.notify_system_health_observation(degraded, confirmations=1) == []
    assert called == []
