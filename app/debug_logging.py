from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

from app.config import DEBUG_LOG_PATH

_HANDLER_NAME = "bbm-debug-file"
_TECHNICAL_MARKERS = (
    "Traceback (most recent call last)",
    "During handling of the above exception",
    "The above exception was the direct cause",
    "ExceptionGroup Traceback",
    "  File \"",
    "  File '",
    "sqlalchemy.exc.",
    "pydantic_core._pydantic_core",
    "starlette.middleware",
    "fastapi.routing",
)
_EXCEPTION_LINE = re.compile(r"(?:^|\n)[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):\s*", re.MULTILINE)


def _level() -> int:
    """Return the fixed incident-log threshold.

    ``debug.log`` is an incident log, not a verbose application log. Its
    threshold is fixed and cannot be lowered through runtime configuration.
    """
    return logging.ERROR


class _IncidentOnlyFilter(logging.Filter):
    """Allow only tracebacks and severe application/framework incidents."""

    _ERROR_LOGGERS = (
        "bbm.",
        "uvicorn.error",
        "fastapi",
        "starlette",
        "app.notifications",
        "app.main",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info or record.stack_info:
            return True
        if record.levelno >= logging.CRITICAL:
            return True
        return record.levelno >= logging.ERROR and record.name.startswith(self._ERROR_LOGGERS)


def _detail_text(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(detail)


def detail_requires_debug_log(detail: Any) -> bool:
    """Return whether an HTTP-visible detail contains technical diagnostics.

    Ordinary validation and Borg summary messages remain visible. Full Python
    tracebacks and framework internals are kept out of the browser and persisted
    in ``debug.log`` instead. Long but otherwise normal Borg, backup or
    source-statistics output is deliberately not treated as an incident.
    """
    text = _detail_text(detail).strip()
    if not text:
        return False
    if any(marker in text for marker in _TECHNICAL_MARKERS):
        return True
    return bool(_EXCEPTION_LINE.search(text) and "\n" in text)


def new_error_id() -> str:
    return f"BBM-{secrets.token_hex(4).upper()}"


def public_error_message(error_id: str) -> str:
    return (
        "Unerwarteter interner Fehler. Details wurden im Debug-Log gespeichert. "
        f"Fehler-ID: {error_id}"
    )


def log_unexpected_exception(
    context: str,
    *,
    exc: BaseException | None = None,
    detail: Any = None,
    method: str | None = None,
    path: str | None = None,
    logger_name: str = "bbm.unexpected",
) -> str:
    """Persist a full unexpected failure and return its public reference ID."""
    error_id = new_error_id()
    location = ""
    if method or path:
        location = f" [{(method or '-').upper()} {path or '-'}]"
    technical = _detail_text(detail).strip()
    message = f"[{error_id}] {context}{location}"
    if technical:
        message += f"\nTechnical detail:\n{technical}"

    active_exc = exc
    if active_exc is None:
        current = sys.exc_info()[1]
        if isinstance(current, BaseException):
            active_exc = current
    logger = logging.getLogger(logger_name)
    if active_exc is not None:
        logger.error(
            message,
            exc_info=(type(active_exc), active_exc, active_exc.__traceback__),
        )
    else:
        logger.error(message)
    return error_id


def configure_debug_logging(path: Path = DEBUG_LOG_PATH) -> None:
    """Capture unexpected application, scheduler and asyncio failures persistently."""
    root = logging.getLogger()
    if any(getattr(handler, "name", "") == _HANDLER_NAME for handler in root.handlers):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.name = _HANDLER_NAME
        handler.setLevel(_level())
        handler.addFilter(_IncidentOnlyFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > handler.level:
            root.setLevel(handler.level)
        # Uvicorn configures its error logger with propagation disabled. Attach
        # the same protected file handler there so lifespan/startup tracebacks
        # are captured as well as application and background-task errors.
        for logger_name in ("uvicorn.error", "uvicorn", "fastapi", "starlette"):
            logger = logging.getLogger(logger_name)
            if not logger.propagate and handler not in logger.handlers:
                logger.addHandler(handler)
        try:
            os.chmod(path, 0o640)
        except OSError:
            pass
    except OSError:
        return

    previous_excepthook = sys.excepthook

    def _sys_hook(exc_type, exc_value, exc_traceback):
        logging.getLogger("bbm.unhandled").critical(
            "Unhandled process exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_excepthook(exc_type, exc_value, exc_traceback)

    if not getattr(sys.excepthook, "_bbm_debug_hook", False):
        _sys_hook._bbm_debug_hook = True
        sys.excepthook = _sys_hook

    previous_thread_hook = threading.excepthook

    def _thread_hook(args):
        logging.getLogger("bbm.thread").critical(
            "Unhandled thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        previous_thread_hook(args)

    if not getattr(threading.excepthook, "_bbm_debug_hook", False):
        _thread_hook._bbm_debug_hook = True
        threading.excepthook = _thread_hook


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop):
    previous = loop.get_exception_handler()

    def _handler(active_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exception = context.get("exception")
        message = context.get("message", "Unhandled asyncio exception")
        if exception is not None:
            logging.getLogger("bbm.asyncio").error(
                message,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        else:
            logging.getLogger("bbm.asyncio").error("%s: %r", message, context)
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)
    return previous
