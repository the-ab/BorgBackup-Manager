from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_hosts_are_stacked_and_mobile_navigation_is_collapsible():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'class="hosts-stack"' in html
    assert 'id="mobile-nav-toggle"' in html
    assert 'aria-controls="main-navigation"' in html
    assert ".hosts-stack" in css
    assert "aside.mobile-open nav" in css
    assert "setMobileNavigation" in javascript
    assert "matchMedia('(max-width: 760px)')" in javascript


def test_repository_ids_and_compact_columns_do_not_compete_with_actions():
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert '<th>Status</th><th>ID</th><th>Repository</th>' in javascript
    assert 'data-label="ID" class="repo-id-cell"' in javascript
    assert 'title="Manager-Repository-ID">#${repo.id}' in javascript
    assert ".repositories-table th:nth-child(1) { width: 8%; }" in css
    assert ".repositories-table th:nth-child(2) { width: 5%; }" in css
    assert ".repositories-table th:nth-child(6) { width: 17%; }" in css
    assert ".repositories-table th:nth-child(7) { width: 27%; }" in css
    assert ".repositories-table td:nth-child(6) { padding-right: 5px; }" in css
    assert ".repositories-table td:nth-child(7) { padding-left: 5px; }" in css
    assert "grid-template-columns: 6.6rem max-content" in css
    assert ".repository-size-grid b { text-align: left; }" in css


def test_all_operational_views_have_mobile_overflow_protection():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    for view in (
        "dashboard", "hosts", "repositories", "jobs", "schedules", "runs",
        "archives", "restore", "backups", "users", "settings", "help", "releases",
    ):
        assert f'id="view-{view}"' in html

    assert "body { overflow-x: hidden; }" in css
    assert ".data-table td," in css
    assert ".archive-stat-grid { grid-template-columns: 1fr 1fr; }" in css
    assert "width: calc(100vw - 16px);" in css
    assert ".help-toc { flex-wrap: nowrap; overflow-x: auto;" in css
