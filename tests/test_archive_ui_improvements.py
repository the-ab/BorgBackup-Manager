from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_archive_view_has_cached_device_filter_and_newest_first_sorting():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="archive-device-filter"' in html
    assert "function sortArchivesNewestFirst" in javascript
    assert "archive_device" in javascript
    assert "Alle Geräte / alle Archive" in javascript
    assert "neueste zuerst" in javascript
    assert "(?:[-:]\\d{2}(?:\\.\\d+)?)?" in javascript
    assert "renderArchives();" in javascript


def test_dashboard_repository_metrics_are_combined_and_diagnostics_can_close():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'id="close-diagnostics"' in html
    assert "resetSystemDiagnostics" in javascript
    assert "Systemdiagnose geschlossen" in javascript
    assert "detail: `Gesamtgröße ${formatBytes(data.counts.repository_size_bytes)}`" in javascript
    assert "repeat(5, minmax(120px, 1fr))" in stylesheet
    assert ".metric small { display: block;" in stylesheet


def test_archive_bulk_delete_and_repository_compact_are_exposed_safely():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="archive-select-visible"' in html
    assert 'id="delete-selected-archives"' in html
    assert "async function deleteArchives(repositoryId, archives)" in javascript
    assert "`/repositories/${repositoryId}/archive-delete`" in javascript
    assert "async function compactRepository(id)" in javascript
    assert "`/repositories/${id}/compact`" in javascript
    assert "repositoryJobs[0]?.id" not in javascript
    assert "repositoryJobs.length === 1 ? repositoryJobs[0].id : null" in javascript
    assert "Mehrere Geräte" in javascript


def test_archive_browser_uses_file_table_with_metadata_columns():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    assert 'class="browser-breadcrumbs"' in html
    for heading in ("Größe", "Typ", "Rechte", "Besitzer", "Geändert"):
        assert heading in javascript
    assert ".archive-browser-table" in css
    assert "entry.mode" in javascript and "entry.user" in javascript


def test_archive_diff_uses_selected_owner_job_and_readable_output():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    runner = (PROJECT_ROOT / "app/runner.py").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'id="archive-diff-context"' in html
    assert "const ownerJobId = firstJobId && secondJobId" in javascript
    assert "archive_owner_job(data.archive, repository_jobs)" in main
    assert "first_owner.id == second_owner.id" in main
    assert "run_label=comparison_label" in main
    assert 'else f"{first_label} ↔ {second_label}"' in main
    assert 'row.action == "diff-archives" and row.job_name_snapshot' in main
    assert 'parts = [*_borg_base("diff")]' in runner
    assert '"--json-lines"' not in runner.split("def diff_archives_command", 1)[1].split("def browse_archive_command", 1)[0]
    assert "ARCHIVVERGLEICH" in runner
