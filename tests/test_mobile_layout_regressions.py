from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_latest_run_uses_three_compact_dashboard_rows():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'class="dashboard-run-stack"' in javascript
    assert 'class="dashboard-run-result"' in javascript
    assert 'class="dashboard-run-trigger"' in javascript
    assert "${esc(runStatusLabel(last.status))}</span> · <span>Dauer</span>" in javascript
    assert "Zeitplan: ${esc(last.schedule_name || schedule)}" in javascript


def test_mobile_dashboard_and_archive_browser_drop_desktop_minimum_widths():
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert ".dashboard-jobs-table,\n  .archive-browser-table" in css
    assert "width: 100%;\n    min-width: 0;" in css
    assert ".dashboard-size-stack {\n    width: 100%;\n    max-width: 16rem;" in css
    assert ".archive-browser-table tbody {\n    display: grid;" in css
    assert "grid-template-columns: 82px minmax(0, 1fr);" in css
    assert ".archive-browser-table input[type=\"checkbox\"]" in css


def test_mobile_archive_cards_wrap_actions_without_large_horizontal_gap():
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert ".archive-row {\n    flex-wrap: wrap;" in css
    assert ".archive-row .archive-main {\n    flex: 1 1 100%;\n    width: 100%;" in css
    assert ".archive-row > .actions {\n    margin-top: 0;" in css


def test_system_diagnostics_use_responsive_status_cards_and_wrapped_logs():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'class="diagnostic-check-grid"' in javascript
    assert 'class="diagnostic-check diagnostic-info"' in javascript
    assert "const diagnosticChecks = [" in javascript
    assert ".diagnostic-check-grid" in css
    assert "#system-diagnostics pre" in css
    assert "white-space: pre-wrap;" in css
    assert "overflow-wrap: anywhere;" in css


def test_compact_job_schedule_and_archive_forms_stack_on_mobile():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'class="job-create-layout"' in html
    assert 'class="schedule-create-layout"' in html
    assert 'class="panel archive-compare archive-compare-compact"' in html
    assert """.job-create-layout,
  .schedule-create-layout,
  .archive-compare-grid { grid-template-columns: 1fr; }""" in css
    assert ".schedule-editor-head { align-items: stretch; flex-direction: column; }" in css
