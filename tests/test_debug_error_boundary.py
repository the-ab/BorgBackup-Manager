from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from app import main as main_module
from app.debug_logging import (
    configure_debug_logging,
    detail_requires_debug_log,
    log_unexpected_exception,
    public_error_message,
)


def _request(path: str = "/api/repositories", method: str = "POST") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 8443),
    })


def _install_temp_debug_log(path: Path):
    root = logging.getLogger()
    previous = list(root.handlers)
    root.handlers = [handler for handler in root.handlers if getattr(handler, "name", "") != "bbm-debug-file"]
    configure_debug_logging(path)
    return root, previous


def _restore_handlers(root, previous):
    added = [handler for handler in root.handlers if handler not in previous]
    for logger_name in ("uvicorn.error", "uvicorn", "fastapi", "starlette"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler for handler in logger.handlers if handler not in added]
    for handler in added:
        handler.flush()
        handler.close()
    root.handlers = previous


def test_technical_detail_detection_keeps_normal_and_long_run_output_visible():
    assert detail_requires_debug_log("Repository name already exists") is False
    assert detail_requires_debug_log("Traceback (most recent call last):\n  File \"x.py\", line 1\nRuntimeError: boom") is True
    assert detail_requires_debug_log("x" * 5000) is False
    assert detail_requires_debug_log(
        "=== Quellenstatistik aktualisieren ===\n"
        + "Quelle /srv/data: 123 Dateien\n" * 300
        + "ERGEBNIS: Ausschlussbereinigte Quellenstatistik erfolgreich aktualisiert."
    ) is False


def test_unexpected_exception_is_written_with_reference_and_traceback(tmp_path):
    path = tmp_path / "debug.log"
    root, previous = _install_temp_debug_log(path)
    try:
        try:
            raise RuntimeError("repository exploded")
        except RuntimeError as exc:
            error_id = log_unexpected_exception("Repository creation failed", exc=exc)
        for handler in root.handlers:
            handler.flush()
        content = path.read_text(encoding="utf-8")
        assert error_id in content
        assert "Repository creation failed" in content
        assert "Traceback (most recent call last)" in content
        assert "RuntimeError: repository exploded" in content
        assert error_id in public_error_message(error_id)
    finally:
        _restore_handlers(root, previous)


def test_debug_file_ignores_normal_application_and_scheduler_messages(tmp_path):
    path = tmp_path / "debug.log"
    root, previous = _install_temp_debug_log(path)
    try:
        logging.getLogger("apscheduler.executors.default").warning("source statistics completed")
        logging.getLogger("app.service").error("normal backup output should not be copied")
        for handler in root.handlers:
            handler.flush()
        assert path.read_text(encoding="utf-8") == ""
    finally:
        _restore_handlers(root, previous)


@pytest.mark.asyncio
async def test_http_traceback_detail_is_hidden_and_logged(tmp_path):
    path = tmp_path / "debug.log"
    root, previous = _install_temp_debug_log(path)
    try:
        try:
            raise RuntimeError("database failure")
        except RuntimeError as cause:
            try:
                raise HTTPException(
                    400,
                    "Traceback (most recent call last):\n  File \"repo.py\", line 4\nRuntimeError: database failure",
                ) from cause
            except HTTPException as exc:
                response = await main_module.compact_http_exception(_request(), exc)
        payload = json.loads(response.body)
        assert response.status_code == 400
        assert payload["detail"].startswith("Unerwarteter interner Fehler.")
        assert "Fehler-ID: BBM-" in payload["detail"]
        assert "Traceback" not in payload["detail"]
        for handler in root.handlers:
            handler.flush()
        content = path.read_text(encoding="utf-8")
        error_id = payload["detail"].split("Fehler-ID: ", 1)[1]
        assert error_id in content
        assert "RuntimeError: database failure" in content
    finally:
        _restore_handlers(root, previous)


@pytest.mark.asyncio
async def test_expected_http_detail_remains_actionable():
    exc = HTTPException(409, "Repository name already exists")
    response = await main_module.compact_http_exception(_request(), exc)
    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "Repository name already exists"}


@pytest.mark.asyncio
async def test_http_504_is_recorded_with_error_reference(tmp_path):
    path = tmp_path / "debug.log"
    root, previous = _install_temp_debug_log(path)
    try:
        response = await main_module.compact_http_exception(
            _request("/api/repositories/1/archives", "GET"),
            HTTPException(504, "Gateway Timeout"),
        )
        payload = json.loads(response.body)
        assert response.status_code == 504
        assert payload["detail"].startswith("Gateway Timeout")
        assert "Fehler-ID BBM-" in payload["detail"]
        for handler in root.handlers:
            handler.flush()
        content = path.read_text(encoding="utf-8")
        assert "HTTP 504 response was recorded" in content
        assert "Gateway Timeout" in content
    finally:
        _restore_handlers(root, previous)


def test_error_toasts_are_shortened_and_run_failures_auto_hide():
    root = Path(__file__).parents[1]
    javascript = (root / "app/static/app.js").read_text(encoding="utf-8")
    stylesheet = (root / "app/static/style.css").read_text(encoding="utf-8")
    assert "function browserSafeErrorMessage(value)" in javascript
    assert "Traceback (most recent call last)" in javascript
    assert "if (!bad) toastTimer = setTimeout(hideToast, 3200);" in javascript
    assert "else if (Number(autoHideMs) > 0) toastTimer = setTimeout(hideToast, Number(autoHideMs));" in javascript
    assert "toast(`Ausführung #${runId} ${label}`, !good, good ? null : 6000);" in javascript
    assert "text.length > 1200" not in javascript
    assert "close.onclick = hideToast" in javascript
    assert "#toast.show { opacity: 1; transform: translateY(0); pointer-events: auto; }" in stylesheet


def test_repository_traceback_is_compacted_and_persisted(tmp_path):
    path = tmp_path / "debug.log"
    root, previous = _install_temp_debug_log(path)
    try:
        raw = (
            "Traceback (most recent call last):\n"
            "  File \"borg/repository.py\", line 4, in open\n"
            "PermissionError: [Errno 13] Permission denied: '/repositories/repo/data/1'\n"
        )
        summary, _details = main_module.compact_repository_error_with_debug(
            "Repository import diagnostic test", "", raw, 2,
        )
        assert "Traceback" not in summary
        assert "Fehler-ID BBM-" in summary
        for handler in root.handlers:
            handler.flush()
        content = path.read_text(encoding="utf-8")
        assert "Repository import diagnostic test" in content
        assert "PermissionError" in content
    finally:
        _restore_handlers(root, previous)
