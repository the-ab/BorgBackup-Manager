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
