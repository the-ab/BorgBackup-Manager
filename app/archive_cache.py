from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import ARCHIVE_CACHE_DIR


CACHE_VERSION = 1


def _cache_path(repository_id: int, consider_checkpoints: bool = False) -> Path:
    repository_id = int(repository_id)
    if repository_id <= 0:
        raise ValueError("Invalid repository ID")
    suffix = "checkpoints" if consider_checkpoints else "regular"
    return ARCHIVE_CACHE_DIR / f"repository-{repository_id}-{suffix}.json"


def load_archive_cache(repository_id: int, consider_checkpoints: bool = False) -> dict[str, Any] | None:
    path = _cache_path(repository_id, consider_checkpoints)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None
    if payload.get("repository_id") != int(repository_id):
        return None
    if bool(payload.get("consider_checkpoints")) != bool(consider_checkpoints):
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("archives"), list):
        return None
    return payload


def store_archive_cache(
    repository_id: int,
    consider_checkpoints: bool,
    data: dict[str, Any],
) -> dict[str, Any]:
    path = _cache_path(repository_id, consider_checkpoints)
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "version": CACHE_VERSION,
        "repository_id": int(repository_id),
        "consider_checkpoints": bool(consider_checkpoints),
        "generated_at": generated_at,
        "data": data,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    return payload


def invalidate_archive_cache(repository_id: int) -> int:
    removed = 0
    for consider_checkpoints in (False, True):
        path = _cache_path(repository_id, consider_checkpoints)
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def archive_cache_size(repository_id: int) -> int:
    total = 0
    for consider_checkpoints in (False, True):
        path = _cache_path(repository_id, consider_checkpoints)
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total
