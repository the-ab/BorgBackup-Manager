from pathlib import Path


def test_notification_center_is_available_without_inline_javascript():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    assert 'data-system-view="notifications"' in html
    assert 'id="view-notifications"' in html
    assert 'id="notification-form"' in html
    assert 'id="notification-delivery-list"' in html
    assert 'onclick=' not in html.lower()
    assert "api('/notifications/settings'" in javascript
    assert "api('/notifications/test'" in javascript
    assert "api('/notifications/deliveries" in javascript


def test_notification_documentation_exists_in_both_languages():
    root = Path(__file__).parents[1]
    assert "### Benachrichtigungszentrale" in (root / "README.de.md").read_text(encoding="utf-8")
    assert "Benachrichtigungszentrale einrichten" in (root / "INSTALLATION.de.md").read_text(encoding="utf-8")
    assert 'id="help-notifications"' in (root / "app/static/help.de.html").read_text(encoding="utf-8")
    assert 'id="help-notifications"' in (root / "app/static/help.en.html").read_text(encoding="utf-8")


def test_system_health_notifications_are_exposed_in_notification_center():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    notifications = (root / "app/notifications.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    assert 'name="system_health_notifications"' in html
    assert "system_health_notifications: form.get('system_health_notifications') === 'on'" in javascript
    assert 'system_health_degraded' in javascript and 'system_health_restored' in javascript
    assert 'system_health_notifications: bool = True' in notifications
    assert 'notify_system_health_observation' in main
    assert 'asyncio.create_task(system_health_watch_loop()' in main
