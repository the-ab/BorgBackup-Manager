from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main as main_module
from app.debug_logging import configure_debug_logging
from app.system_diagnostics import repository_access_diagnostic


def access(enabled: bool, public_key: str | None = "ssh-ed25519 AAAA"):
    return SimpleNamespace(host=SimpleNamespace(enabled=enabled), public_key=public_key)


def test_disabled_device_access_rows_do_not_fail_diagnostics():
    state = repository_access_diagnostic([access(False)], [])
    assert state["repository_access_rows"] == 0
    assert state["repository_access_ready_rows"] == 0
    assert state["repository_access_inactive_rows"] == 1
    assert state["all_keys_use_forced_command"] is True
    assert state["repository_access_complete"] is True


def test_active_device_access_still_requires_key_and_authorized_line():
    missing = repository_access_diagnostic([access(True, None)], [])
    assert missing["all_keys_use_forced_command"] is True
    assert missing["repository_access_complete"] is False

    line = 'restrict,command="/usr/local/bin/bbm-borg-serve --repository /repositories/repo" ssh-ed25519 AAAA bbm-access-h1-r1'
    ready = repository_access_diagnostic([access(True)], [line])
    assert ready["all_keys_use_forced_command"] is True
    assert ready["repository_access_complete"] is True


def test_repository_browser_lists_root_and_marks_only_direct_repository_selectable(tmp_path, monkeypatch):
    root = tmp_path / "repositories"
    root.mkdir()
    repository = root / "primary"
    repository.mkdir()
    (repository / "config").write_text("[repository]\nid = abc\n", encoding="utf-8")
    nested = root / "group" / "nested"
    nested.mkdir(parents=True)
    (nested / "config").write_text("[repository]\nid = def\n", encoding="utf-8")
    (root / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(main_module, "REPOSITORY_ROOT", root)

    listing = main_module.browse_repository_directories("")
    primary = next(item for item in listing["entries"] if item["name"] == "primary")
    assert primary["is_repository"] is True
    assert primary["selectable"] is True

    nested_listing = main_module.browse_repository_directories("group")
    nested_item = next(item for item in nested_listing["entries"] if item["name"] == "nested")
    assert nested_item["is_repository"] is True
    assert nested_item["selectable"] is False


def test_repository_browser_rejects_traversal_and_symlinks(tmp_path, monkeypatch):
    root = tmp_path / "repositories"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(main_module, "REPOSITORY_ROOT", root)

    with pytest.raises(HTTPException):
        main_module.browse_repository_directories("../outside")
    with pytest.raises(HTTPException):
        main_module.browse_repository_directories("link")


def test_debug_logger_persists_unhandled_errors(tmp_path):
    root = logging.getLogger()
    previous = list(root.handlers)
    try:
        root.handlers = [handler for handler in root.handlers if getattr(handler, "name", "") != "bbm-debug-file"]
        path = tmp_path / "debug.log"
        configure_debug_logging(path)
        logging.getLogger("bbm.test").error("background failure test")
        for handler in root.handlers:
            handler.flush()
        assert "background failure test" in path.read_text(encoding="utf-8")
    finally:
        added = [handler for handler in root.handlers if handler not in previous]
        for logger_name in ("uvicorn.error", "uvicorn", "fastapi", "starlette"):
            logger = logging.getLogger(logger_name)
            logger.handlers = [handler for handler in logger.handlers if handler not in added]
        for handler in added:
            handler.close()
        root.handlers = previous


def test_ui_contains_diagnostic_log_tabs_and_repository_browser():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    entrypoint = (root / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'id="browse-repositories"' in html
    assert 'id="repository-folder-browser"' in html
    assert "/repositories/browse?path=" in javascript
    assert 'data-diagnostic-log="sshd"' in javascript
    assert 'data-diagnostic-log="borg"' in javascript
    assert 'data-diagnostic-log="debug"' in javascript
    assert "/data/logs/debug.log" in entrypoint
    assert "rotate_log /data/logs/debug.log" in entrypoint
