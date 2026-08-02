from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import ACCESS_LOG_PATH, LOG_MAX_BYTES, LOG_ROTATIONS

_LOGGER_NAME = 'bbm.access'
_HANDLER_NAME = 'bbm-access-file'
_LOCK = threading.Lock()


def configure_access_logging() -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    existing = [handler for handler in logger.handlers if getattr(handler, 'name', '') == _HANDLER_NAME]
    if existing and ACCESS_LOG_PATH.exists():
        return
    for handler in existing:
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    ACCESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(ACCESS_LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_ROTATIONS, encoding='utf-8')
    handler.name = _HANDLER_NAME
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    try:
        ACCESS_LOG_PATH.chmod(0o600)
    except OSError:
        pass


def write_access_event(event: str, *, remote_address: str | None = None, username: str | None = None,
                       status: str | None = None, method: str | None = None, path: str | None = None,
                       http_status: int | None = None, user_agent: str | None = None, detail: str | None = None,
                       duration_ms: float | None = None, **extra: Any) -> None:
    try:
        configure_access_logging()
    except Exception:
        return
    payload: dict[str, Any] = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'event': event,
        'remote_address': remote_address or '',
    }
    optional = {
        'username': username, 'status': status, 'method': method, 'path': path,
        'http_status': http_status, 'user_agent': (user_agent or '')[:500],
        'detail': (detail or '')[:1000], 'duration_ms': round(duration_ms, 3) if duration_ms is not None else None,
    }
    payload.update({key: value for key, value in optional.items() if value not in (None, '')})
    payload.update({key: value for key, value in extra.items() if value is not None})
    try:
        with _LOCK:
            logger = logging.getLogger(_LOGGER_NAME)
            logger.info(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str))
            for handler in logger.handlers:
                try:
                    handler.flush()
                except Exception:
                    pass
    except Exception:
        # Access logging must never break authentication or API responses.
        return
