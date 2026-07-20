from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

from app.config import DEBUG_LOG_PATH

_HANDLER_NAME = "bbm-debug-file"


def _level() -> int:
    name = os.getenv("BBM_DEBUG_LOG_LEVEL", "WARNING").strip().upper()
    return getattr(logging, name, logging.WARNING) if name in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else logging.WARNING


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
        logging.getLogger("bbm.unhandled").critical("Unhandled process exception", exc_info=(exc_type, exc_value, exc_traceback))
        previous_excepthook(exc_type, exc_value, exc_traceback)
    if not getattr(sys.excepthook, "_bbm_debug_hook", False):
        _sys_hook._bbm_debug_hook = True
        sys.excepthook = _sys_hook

    previous_thread_hook = threading.excepthook
    def _thread_hook(args):
        logging.getLogger("bbm.thread").critical(
            "Unhandled thread exception in %s", getattr(args.thread, "name", "unknown"),
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
            logging.getLogger("bbm.asyncio").error(message, exc_info=(type(exception), exception, exception.__traceback__))
        else:
            logging.getLogger("bbm.asyncio").error("%s: %r", message, context)
        if previous is not None:
            previous(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)
    return previous
