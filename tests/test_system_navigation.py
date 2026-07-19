from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_system_workspace_replaces_individual_sidebar_entries():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    infrastructure = html.split('<span class="nav-label">Infrastruktur</span>', 1)[1].split('<span class="nav-label">Information</span>', 1)[0]
    assert 'data-view="hosts">Geräte</button>' in infrastructure
    assert 'data-view="settings">System</button>' in infrastructure
    assert 'data-view="backups"' not in infrastructure
    assert 'data-view="notifications"' not in infrastructure
    assert 'data-view="users"' not in infrastructure

    tabs = html.split('id="system-workspace-tabs"', 1)[1].split('</div>', 1)[0]
    expected = [
        'data-system-view="notifications"',
        'data-system-view="users"',
        'data-system-view="backups"',
        'data-system-view="settings"',
        'data-system-view="diagnostics"',
    ]
    positions = [tabs.index(item) for item in expected]
    assert positions == sorted(positions)
    assert "const SYSTEM_VIEWS = new Set(['notifications', 'users', 'backups', 'settings', 'diagnostics']);" in javascript
    assert "const sidebarView = systemView ? 'settings' : view;" in javascript
    assert "$('#page-title').textContent = systemView ? 'System'" in javascript


def test_system_diagnostics_is_not_rendered_on_dashboard():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    dashboard = html.split('id="view-dashboard"', 1)[1].split('id="view-hosts"', 1)[0]
    diagnostics = html.split('id="view-diagnostics"', 1)[1].split('id="view-help"', 1)[0]

    assert 'id="system-diagnostics"' not in dashboard
    assert 'id="load-diagnostics"' not in dashboard
    assert 'id="system-diagnostics"' in diagnostics
    assert 'id="load-diagnostics"' in diagnostics
    assert 'id="close-diagnostics"' in diagnostics


def test_system_tabs_have_responsive_styling_and_documentation():
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.de.md").read_text(encoding="utf-8")
    installation = (PROJECT_ROOT / "INSTALLATION.de.md").read_text(encoding="utf-8")

    assert ".system-workspace-tabs" in css
    assert "overflow-x: auto" in css
    assert "Benachrichtigungen" in readme and "Systemdiagnose" in readme
    assert "Unter **Infrastruktur**" in installation
    assert "Die Systemdiagnose wurde vom Dashboard" in installation


def test_system_tabs_are_inside_sticky_header_and_active_is_visibly_filled():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    header = html.split('<header class="main-header">', 1)[1].split('</header>', 1)[0]
    assert 'id="system-workspace-tabs"' in header
    assert header.count('class="system-tab"') == 5
    assert 'main > header' in css and 'position: sticky' in css
    active = css.split('.system-workspace-tabs button.active', 1)[1].split('}', 1)[0]
    assert 'background: var(--system-tab-active)' in active
    assert 'color: #fff' in active
    assert '--system-tab-active: #174c46' in css
    assert '--system-tab-active: #2f7f70' in css
    generic = css.split('button:not(.link)', 1)[1].split('{', 1)[0]
    assert ':not(.system-tab)' in generic


def test_system_tabs_resynchronize_after_session_restore_and_permissions():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert "function syncSystemWorkspaceNavigation(view = hashView())" in javascript
    apply_permissions = javascript.split("function applyUserPermissions()", 1)[1].split("function parseHashState()", 1)[0]
    assert "syncSystemWorkspaceNavigation(hashView());" in apply_permissions
    restore = javascript.split("async function restoreBrowserSession()", 1)[1]
    assert "applyUserPermissions();\n    goToView(hashView(), false);" in restore
    assert '.system-workspace-tabs button[aria-selected="true"]' in css
    assert ':not(.system-tab)' in css
    assert 'aria-current' in javascript
    assert 'background: var(--system-tab-active)' in css


def test_markdown_defaults_are_english_and_german_uses_de_suffix():
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_de = (PROJECT_ROOT / "README.de.md").read_text(encoding="utf-8")
    install_en = (PROJECT_ROOT / "INSTALLATION.md").read_text(encoding="utf-8")
    install_de = (PROJECT_ROOT / "INSTALLATION.de.md").read_text(encoding="utf-8")
    notes_en = (PROJECT_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    notes_de = (PROJECT_ROOT / "RELEASE_NOTES.de.md").read_text(encoding="utf-8")
    assert "self-hosted web interface" in readme_en
    assert "zentrale Webverwaltung" in readme_de
    assert "Manager host requirements" in install_en
    assert "Voraussetzungen des Manager-Hosts" in install_de
    assert "System tab active state" in notes_en
    assert "Aktive Markierung der System-Reiter" in notes_de
    assert (PROJECT_ROOT / "app/RELEASE_NOTES.md").is_file()
    assert (PROJECT_ROOT / "app/RELEASE_NOTES.de.md").is_file()
