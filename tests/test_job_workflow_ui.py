from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_repository_access_is_managed_directly_from_backup_jobs():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert "async function bootstrapJob" in javascript
    assert "`/jobs/${id}/bootstrap-repository`" in javascript
    assert "Repository-Zugang zuerst einrichten" in javascript
    assert "Zugang erneuern" in javascript
    assert "onclick=\"bootstrapHost" not in javascript
    help_de = (PROJECT_ROOT / "app/static/help.de.html").read_text(encoding="utf-8")
    assert "Einrichtung und Erneuerung erfolgen" in help_de
    assert "jeweiligen Backup-Job" in help_de


def test_dashboard_backup_jobs_have_direct_start_action():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert '<th>Aktion</th>' in javascript
    assert "bbmAction('action', job.id, 'backup')" in javascript
    assert "repository_access_ready" in javascript
    assert "Backup jetzt manuell starten" in javascript


def test_run_dialog_keeps_log_scrollbar_visible_with_warnings():
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert ".run-dialog[open]" in css
    assert "display: flex" in css
    assert "height: min(900px, calc(100dvh - 24px))" in css
    assert ".run-dialog .log-view.active" in css
    assert "min-height: 150px" in css
    assert ".run-dialog #log-view-output.active .log-console" in css


def test_device_onboarding_copies_controller_key_and_confirms_fingerprint_inline():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'id="copy-controller-key"' in html
    assert "Controller-Schlüssel kopiert" in javascript
    assert 'id="host-fingerprint-actions"' in html
    assert 'id="accept-host-key"' in html
    assert "showPendingHostKey" in javascript
    assert "acceptPendingHostKey" in javascript
    assert "SSH-Fingerprint ${result.fingerprint}" not in javascript
    assert ".fingerprint-box" in css



def test_controller_key_copy_is_inline_and_rotation_is_only_in_settings():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    host_section = html.split('id="view-hosts"', 1)[1].split('id="view-repositories"', 1)[0]
    settings_section = html.split('id="view-settings"', 1)[1].split('id="view-help"', 1)[0]
    assert 'class="key-copy-row"' in host_section
    assert 'id="copy-controller-key"' in host_section
    assert 'id="rotate-controller-key"' not in host_section
    assert 'id="settings-controller-key-section"' in settings_section
    assert 'id="rotate-controller-key"' in settings_section
    assert 'id="open-controller-key-settings"' in host_section
    assert "$('#settings-copy-controller-key').onclick = copyControllerKey" in javascript
    assert '.key-copy-row' in css


def test_frontend_logs_out_only_for_real_http_401():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'class ApiError extends Error' in javascript
    assert "response.status === 401" in javascript
    assert "includes('session')" not in javascript
    assert "includes('token')" not in javascript
    assert "async function verifyBrowserSession()" in javascript
    assert "const verifiedUser = await verifyBrowserSession()" in javascript
    assert "Sitzung konnte nicht wiederhergestellt werden" in javascript


def test_expanded_job_actions_use_compact_grouped_toolbar():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'class="job-action-group job-action-group-wide"' in javascript
    assert 'class="job-action-buttons"' in javascript
    assert 'class="job-action-note"' in javascript
    assert "grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))" in css
    assert ".job-action-buttons { display: flex; flex-wrap: wrap" in css
    assert ".job-action-buttons button" in css
    assert "width: auto" in css


def test_warning_runs_show_structured_causes_without_hiding_live_log():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'id="log-warning-causes"' in html
    assert "function renderWarningCauses" in javascript
    assert "run.warning_summary" in javascript
    assert "Warnungsursachen" in javascript
    assert ".warning-cause-list" in css
    assert "max-height: min(25vh, 220px)" in css


def test_list_actions_include_direct_enable_disable_and_backup_upload():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert "bbmAction('setHostEnabled'" in javascript
    assert "bbmAction('setJobEnabled'" in javascript
    assert "setHostEnabled" in javascript and "setJobEnabled" in javascript
    assert "will also be disabled automatically" in javascript
    assert "werden automatisch ebenfalls deaktiviert" in javascript
    assert "Backup-Jobs bleiben deaktiviert" in javascript
    assert 'id="backup-upload-form"' in html
    assert "'/backups/upload'" in javascript
    assert "X-BBM-Backup-Name" in javascript


def test_job_list_shows_refreshable_source_statistics():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "function sourceStatsLine" in javascript
    assert "Quellenstatistik:" in javascript
    assert "'source-stats'" in javascript
    assert "source_file_count" in javascript
    assert "Live-Scan vor Ausschlüssen" in javascript


def test_job_list_has_direct_edit_button_before_more_actions():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    sequence = "Archive</button><button class=\"secondary\" ${bbmAction('editJob', job.id)}>Bearbeiten</button><button class=\"secondary\" data-job-toggle="
    assert sequence in javascript
    assert ">Job bearbeiten</button>" not in javascript


def test_job_editor_uses_left_space_and_keeps_paths_at_top_right():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    basics = html.split('class="job-create-basics"', 1)[1].split('class="job-create-paths"', 1)[0]
    paths = html.split('class="job-create-paths"', 1)[1].split('<details class="job-options"', 1)[0]
    assert "Archivnamensvorlage" in basics and "Kompression" in basics
    assert paths.index("Quellpfade") < paths.index("Ausschlussvorlage") < paths.index("Ausschlüsse")
    assert ".job-create-paths { align-self: start; }" in css
    assert "@media (max-width: 820px)" in css
