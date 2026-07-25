from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import UPDATE_STATUS_PATH

GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/the-ab/BorgBackup-Manager/releases/latest"
GITHUB_RELEASE_BASE = "https://github.com/the-ab/BorgBackup-Manager/releases/tag/"
_VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MAX_RESPONSE_BYTES = 1024 * 1024
_lock = Lock()
_cached_status: dict | None = None


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"Ungültige Release-Version: {value!r}")
    return tuple(int(part) for part in match.groups())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_status(current_version: str) -> dict:
    return {
        "current_version": current_version,
        "latest_version": None,
        "update_available": None,
        "release_url": None,
        "checked_at": None,
        "last_attempt_at": None,
        "error": None,
    }


def _load_status_uncached(current_version: str) -> dict:
    status = _default_status(current_version)
    try:
        raw = json.loads(UPDATE_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return status
    if not isinstance(raw, dict):
        return status
    for key in status:
        if key in raw:
            status[key] = raw[key]
    status["current_version"] = current_version
    latest = status.get("latest_version")
    if latest:
        try:
            status["update_available"] = version_tuple(latest) > version_tuple(current_version)
        except ValueError:
            status["latest_version"] = None
            status["update_available"] = None
            status["release_url"] = None
    return status


def load_update_status(current_version: str) -> dict:
    global _cached_status
    with _lock:
        if _cached_status is None or _cached_status.get("current_version") != current_version:
            _cached_status = _load_status_uncached(current_version)
        return dict(_cached_status)


def _store_status(status: dict) -> dict:
    global _cached_status
    UPDATE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = UPDATE_STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(UPDATE_STATUS_PATH)
    with _lock:
        _cached_status = dict(status)
    return dict(status)


def check_latest_release(current_version: str, *, timeout: float = 10.0) -> dict:
    previous = load_update_status(current_version)
    attempt_at = _now_iso()
    request = Request(
        GITHUB_LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"BorgBackup-Manager/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise ValueError("GitHub-Antwort ist unerwartet groß")
        data = json.loads(payload.decode("utf-8"))
        tag = str(data.get("tag_name") or "").strip()
        latest = tag[1:] if tag.startswith("v") else tag
        version_tuple(latest)
        current = version_tuple(current_version)
        release_url = GITHUB_RELEASE_BASE + quote(tag, safe="._-")
        return _store_status({
            "current_version": current_version,
            "latest_version": latest,
            "update_available": version_tuple(latest) > current,
            "release_url": release_url,
            "checked_at": attempt_at,
            "last_attempt_at": attempt_at,
            "error": None,
        })
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        failed = dict(previous)
        failed["current_version"] = current_version
        failed["last_attempt_at"] = attempt_at
        failed["error"] = str(exc)[:500] or exc.__class__.__name__
        return _store_status(failed)
