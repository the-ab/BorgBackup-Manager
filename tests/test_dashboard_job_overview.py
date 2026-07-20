from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_dashboard_contains_backup_job_block_before_recent_activity():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")

    job_block = html.index('id="dashboard-jobs"')
    recent_runs = html.index('id="recent-runs"')
    assert job_block < recent_runs
    assert "Alle Backup-Jobs" in html


def test_dashboard_job_table_and_run_details_show_requested_metadata():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    for heading in (
        "Status", "Job", "Gerät", "Repository", "Quellen", "Zeitplan",
        "Letzter Job", "Größe letzte Sicherung",
    ):
        assert heading in javascript
    assert "last_successful_backup" in javascript
    assert "trigger_type === 'schedule'" in javascript
    assert "Backup-Größe" in javascript
    assert "Dedupliziert" in javascript


def test_dashboard_uses_compact_stacked_job_metadata_blocks():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'class="dashboard-size-stack"' in javascript
    assert 'class="dashboard-run-stack"' in javascript
    assert 'class="source-stat-copy"' in javascript
    assert 'class="dashboard-run-result"' in javascript
    assert '<span>Dauer</span> ${esc(formatDuration(last.duration_seconds))}' in javascript
    assert 'class="dashboard-run-trigger"' in javascript
    assert "const sourceLabel = job.source_stats_origin === 'scan' ? 'Live-Scan vor Ausschlüssen' : 'Letztes Backup'" in javascript
    assert "${sourceLabel} · ${esc(checked)}" in javascript
    assert ".dashboard-size-stack > span" in stylesheet
    assert "grid-template-columns: minmax(6.8rem, 1fr) auto" in stylesheet


def test_dashboard_inline_warning_status_does_not_inherit_warning_box_spacing():
    stylesheet = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert ".warning:not(.badge):not(.status-text)" in stylesheet
    assert ".notice, .warning:not(.badge):not(.status-text), .diagnosis-box" in stylesheet
    assert "body.compact .warning:not(.badge):not(.status-text)" in stylesheet
    assert ".status-text.warning { color: var(--warning); }" in stylesheet
    assert ".warning { background: var(--warning-soft); color: var(--warning); }" not in stylesheet
