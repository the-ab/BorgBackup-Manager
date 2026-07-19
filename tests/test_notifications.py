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
    from app.security_store import delete_secret
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
