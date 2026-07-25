from __future__ import annotations

import json
from pathlib import Path

import app.update_check as update_check
from app.schemas import SettingsIn


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self.payload


def reset_cache(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "update-status.json"
    monkeypatch.setattr(update_check, "UPDATE_STATUS_PATH", path)
    monkeypatch.setattr(update_check, "_cached_status", None)
    return path


def test_version_tuple_accepts_release_tags():
    assert update_check.version_tuple("1.0.73") == (1, 0, 73)
    assert update_check.version_tuple("v2.3.4") == (2, 3, 4)


def test_update_check_detects_newer_release_and_persists(monkeypatch, tmp_path):
    status_path = reset_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(update_check, "urlopen", lambda request, timeout: FakeResponse({"tag_name": "v1.0.74"}))

    result = update_check.check_latest_release("1.0.73")

    assert result["update_available"] is True
    assert result["latest_version"] == "1.0.74"
    assert result["release_url"] == "https://github.com/the-ab/BorgBackup-Manager/releases/tag/v1.0.74"
    assert result["checked_at"]
    assert json.loads(status_path.read_text(encoding="utf-8"))["latest_version"] == "1.0.74"


def test_update_check_marks_same_version_current(monkeypatch, tmp_path):
    reset_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(update_check, "urlopen", lambda request, timeout: FakeResponse({"tag_name": "v1.0.73"}))

    result = update_check.check_latest_release("1.0.73")

    assert result["update_available"] is False
    assert result["latest_version"] == "1.0.73"


def test_settings_have_safe_update_defaults():
    settings = SettingsIn()
    assert settings.update_check_enabled is True
    assert settings.update_check_interval_hours == 24


def test_sidebar_order_settings_and_mobile_live_dialog_are_present():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    js = (root / "app/static/app.js").read_text(encoding="utf-8")
    css = (root / "app/static/style.css").read_text(encoding="utf-8")

    service = html.index('class="service-status-row"')
    update = html.index('id="update-status-link"')
    version = html.index('id="version-link"')
    assert service < update < version
    assert 'name="update_check_enabled"' in html
    assert 'name="update_check_interval_hours"' in html
    assert 'id="check-updates-now"' in html
    assert 'class="run-dialog-body"' in html
    assert 'backup-progress-last-status' in js
    assert "document.body.classList.add('run-dialog-open')" in js
    assert 'body.run-dialog-open { overflow: hidden; }' in css
    assert '.run-dialog-body {' in css and 'overflow-y: auto;' in css


def test_scheduler_preserves_release_check_cadence(monkeypatch):
    from datetime import datetime, timezone
    import app.main as main

    monkeypatch.setattr(
        main,
        "load_update_status",
        lambda _version: {
            "checked_at": "2026-07-25T10:00:00+00:00",
            "last_attempt_at": "2026-07-25T12:00:00+00:00",
        },
    )
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 7, 25, 13, 0, 0, tzinfo=timezone.utc)
            return value if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(main, "datetime", FixedDatetime)
    assert main._update_check_next_run(24) == FixedDatetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
    assert main._update_check_next_run(24, immediate=True) == FixedDatetime(2026, 7, 25, 13, 0, 0, tzinfo=timezone.utc)


def test_schedule_rebuild_does_not_force_release_check():
    root = Path(__file__).parents[1]
    source = (root / "app/main.py").read_text(encoding="utf-8")
    assert "sync_update_check_job(immediate=False)" in source
