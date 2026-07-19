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
