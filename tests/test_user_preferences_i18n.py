from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


PROJECT_ROOT = Path(__file__).parents[1]


def test_user_preferences_are_persisted_and_returned_by_auth_status():
    username = f'pref-{uuid4().hex[:12]}'
    password = 'Preferences-Test-1!'
    admin_headers = {'Authorization': 'Bearer test-token'}
    with TestClient(app, base_url='https://testserver') as client:
        created = client.post('/api/users', headers=admin_headers, json={
            'username': username, 'password': password, 'password_confirm': password,
            'role': 'user', 'must_change_password': False,
        })
        assert created.status_code == 201
        user_id = created.json()['id']
        login = client.post('/api/auth/login', headers={'X-BBM-Request': '1'}, json={'username': username, 'password': password})
        assert login.status_code == 200
        assert login.json()['language'] == 'de'
        assert login.json()['appearance'] == 'auto'
        updated = client.put('/api/auth/preferences', headers={'X-BBM-Request': '1'}, json={'language': 'en', 'appearance': 'dark'})
        assert updated.status_code == 200
        assert updated.json()['language'] == 'en'
        assert updated.json()['appearance'] == 'dark'
        status = client.get('/api/auth/status')
        assert status.status_code == 200
        assert status.json()['language'] == 'en'
        assert status.json()['appearance'] == 'dark'
        assert client.delete(f'/api/users/{user_id}', headers=admin_headers).status_code == 204


def test_language_and_theme_controls_are_per_user_not_global_settings():
    html = (PROJECT_ROOT / 'app/static/index.html').read_text(encoding='utf-8')
    javascript = (PROJECT_ROOT / 'app/static/app.js').read_text(encoding='utf-8')
    schemas = (PROJECT_ROOT / 'app/schemas.py').read_text(encoding='utf-8')
    security = (PROJECT_ROOT / 'app/security_store.py').read_text(encoding='utf-8')

    assert 'id="preferences-dialog"' in html
    assert 'name="language"' in html
    assert 'name="appearance"' in html
    settings_section = html.split('id="view-settings"', 1)[1].split('id="view-help"', 1)[0]
    assert 'select name="appearance"' not in settings_section
    assert "api('/auth/preferences'" in javascript
    assert "state.currentUser.appearance" in javascript
    assert "state.settings.appearance = theme" not in javascript
    assert 'class UserPreferencesIn' in schemas
    assert 'def update_user_preferences' in security


def test_german_and_english_ui_resources_cover_all_main_areas():
    html = (PROJECT_ROOT / 'app/static/index.html').read_text(encoding='utf-8')
    i18n = (PROJECT_ROOT / 'app/static/i18n.js').read_text(encoding='utf-8')
    help_de = (PROJECT_ROOT / 'app/static/help.de.html').read_text(encoding='utf-8')
    help_en = (PROJECT_ROOT / 'app/static/help.en.html').read_text(encoding='utf-8')

    assert '/static/i18n.js?v=' in html
    assert "'Backup-Jobs': 'Backup jobs'" in i18n
    assert "'Repository hinzufügen': 'Add repository'" in i18n
    assert "'Manager-Repository-ID': 'Manager repository ID'" in i18n
    assert "'Wiederherstellung starten': 'Start restore'" in i18n
    assert "'Ausgewählte Archive löschen': 'Delete selected archives'" in i18n
    assert "'Mehrere Geräte': 'Multiple devices'" in i18n
    assert "'Compact direkt am Repository': 'Compact directly on repository'" in i18n
    assert 'MutationObserver' in i18n
    for section in ('start', 'security', 'dashboard', 'hosts', 'repositories', 'jobs', 'schedules', 'runs', 'archives', 'restore', 'backups', 'users', 'settings', 'diagnostics'):
        assert f'id="help-{section}"' in help_de
        assert f'id="help-{section}"' in help_en
    assert 'current running task' in help_en
    assert 'aktuell laufenden Vorgang' in help_de


def test_release_notes_endpoint_follows_requested_language():
    headers = {'Authorization': 'Bearer test-token'}
    with TestClient(app, base_url='https://testserver') as client:
        german = client.get('/api/system/release-notes?language=de', headers=headers)
        english = client.get('/api/system/release-notes?language=en', headers=headers)
    assert german.status_code == 200
    assert english.status_code == 200
    assert 'Statusanzeige öffnet direkt' in german.json()['content']
    assert 'Direct live-log access' in english.json()['content']


def test_release_package_includes_bilingual_release_notes():
    dockerfile = (PROJECT_ROOT / 'Dockerfile').read_text(encoding='utf-8')
    updater = (PROJECT_ROOT / 'update.sh').read_text(encoding='utf-8')
    assert 'COPY README.md INSTALLATION.md RELEASE_NOTES.md ./' in dockerfile
    assert 'COPY README.md INSTALLATION.md RELEASE_NOTES.md RELEASE_NOTES.en.md ./' not in dockerfile
    assert (PROJECT_ROOT / 'app/RELEASE_NOTES.en.md').is_file()
    assert 'RELEASE_NOTES.en.md' in updater


def test_translation_observer_does_not_rewrite_identical_values():
    """Identical writes would recursively retrigger MutationObserver callbacks."""
    i18n = (PROJECT_ROOT / 'app/static/i18n.js').read_text(encoding='utf-8')
    assert "if (node.nodeValue !== translated) node.nodeValue = translated;" in i18n
    assert "if (value !== translated) element.setAttribute(name, translated);" in i18n
    assert "node.nodeValue = currentLanguage === 'de' ? source : translateRaw(source);" not in i18n
    assert "element.setAttribute(name, currentLanguage === 'de' ? source : translateRaw(source));" not in i18n
