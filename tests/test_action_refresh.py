from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_actions_have_visible_and_targeted_refresh_feedback():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'id="sync-state"' in html
    assert 'aria-live="polite"' in html
    assert "function setSyncState" in javascript
    assert "function markButtonBusy" in javascript
    assert "async function performAreaRefresh" in javascript
    assert "function refreshAreas" in javascript
    assert ".sync-state.pending" in stylesheet
    assert "button.action-busy" in stylesheet


def test_background_runs_refresh_only_after_real_completion():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert "function watchRunCompletion" in javascript
    assert "async function pollRun" in javascript
    assert "activeRunStatus(run.status)" in javascript
    assert "await refreshAreas(tracker.areas" in javascript
    assert "setTimeout(loadAll, 600)" not in javascript
    assert "setTimeout(() => loadAll(true), 500)" not in javascript


def test_api_reads_bypass_browser_cache_for_immediate_confirmation():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    api_start = javascript.index("async function api(")
    api_end = javascript.index("let loginInProgress", api_start)
    api_block = javascript[api_start:api_end]
    assert "cache: 'no-store'" in api_block


def test_forms_and_repository_actions_confirm_without_full_page_reload():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert "markButtonBusy(event.submitter" in javascript
    assert "Repository-Verbindung wird geprüft" in javascript
    assert "Repository-Cache wird gelöscht" in javascript
    assert "Gespeicherte Änderungen werden angezeigt" in javascript
    assert "toast('Gespeichert'); loadAll();" not in javascript


def test_header_status_opens_only_the_current_active_run_live_log():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="sync-state"' in html
    assert 'id="task-status-menu"' not in html
    assert "api('/runs?status=active&limit=100')" in javascript
    assert "function currentActiveRun" in javascript
    assert "run.status === 'running'" in javascript
    assert "function openCurrentActiveRun" in javascript
    assert "if (run) showRun(run.id)" in javascript
    assert "$('#sync-state').onclick = openCurrentActiveRun" in javascript
    assert "toggleTaskStatusMenu" not in javascript


def test_live_polling_avoids_full_log_reads_when_dialog_is_closed():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert "?include_details=false" in javascript
    assert "?live=true&log_offset=" in javascript
    assert "liveDialogOpen ? 1800 : 1500" in javascript
    assert "run = await api('/runs/' + runId);" in javascript
    assert "state.liveLogOffset" in javascript
    assert "appendLog: true" in javascript


def test_live_dialog_serializes_offset_requests_and_replaces_empty_placeholder():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert "liveLogRequestPending" in javascript
    assert "liveLogSession" in javascript
    assert "currentOffset === requestedOffset" in javascript
    assert "Ignore a stale response" in javascript
    assert "emptyPlaceholder" in javascript
    assert "logContent.textContent = '';" in javascript


def test_empty_incremental_log_delta_never_reuses_sqlite_preview():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert "const rawReadable = appendLog" in javascript
    assert "String(run.log_output ?? '')" in javascript
    assert "already displayed header would be appended again" in javascript
