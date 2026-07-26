from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

_lock = Lock()
_tasks: dict[str, dict[str, Any]] = {}
_current_task_id: str | None = None
_MAX_TASKS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def begin_task(
    task_id: str,
    *,
    label: str,
    backup_type: str = "manager",
    include_borg_cache: bool = False,
    include_client_borg_cache: bool = False,
) -> dict[str, Any]:
    global _current_task_id
    with _lock:
        if _current_task_id:
            current = _tasks.get(_current_task_id)
            if current and current.get("status") in {"queued", "running"}:
                raise ValueError("Es wird bereits ein Manager-Backup erstellt")
        if backup_type not in {"manager", "cache"}:
            raise ValueError("Unbekannter Backup-Typ")
        initial_message = "Cache-Backup wird vorbereitet …" if backup_type == "cache" else "Manager-Backup wird vorbereitet …"
        task = {
            "id": task_id,
            "backup_type": backup_type,
            "status": "queued",
            "stage": "queued",
            "message": initial_message,
            "percent": 0.0,
            "label": label,
            "include_borg_cache": bool(include_borg_cache),
            "include_client_borg_cache": bool(include_client_borg_cache),
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "current": None,
            "total": None,
            "bytes_done": 0,
            "backup": None,
            "error": None,
            "events": [{"at": _now(), "message": initial_message}],
        }
        _tasks[task_id] = task
        _current_task_id = task_id
        _prune_locked()
        return deepcopy(task)


def update_task(task_id: str, **changes: Any) -> dict[str, Any] | None:
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        if task.get("started_at") is None and changes.get("status", task.get("status")) == "running":
            task["started_at"] = _now()
        message = changes.get("message")
        if message and message != task.get("message"):
            events = task.setdefault("events", [])
            events.append({"at": _now(), "message": str(message)})
            del events[:-12]
        task.update(changes)
        task["updated_at"] = _now()
        return deepcopy(task)


def finish_task(task_id: str, *, backup: dict[str, Any] | None = None) -> dict[str, Any] | None:
    global _current_task_id
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        noun = "Cache-Backup" if task.get("backup_type") == "cache" else "Manager-Backup"
        success_message = f"{noun} wurde erfolgreich erstellt."
        task.setdefault("events", []).append({"at": _now(), "message": success_message})
        del task["events"][:-12]
        task.update({
            "status": "finished",
            "stage": "finished",
            "message": success_message,
            "percent": 100.0,
            "finished_at": _now(),
            "backup": backup,
            "error": None,
            "updated_at": _now(),
        })
        if _current_task_id == task_id:
            _current_task_id = None
        _prune_locked()
        return deepcopy(task)


def fail_task(task_id: str, error: str) -> dict[str, Any] | None:
    global _current_task_id
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        noun = "Cache-Backup" if task.get("backup_type") == "cache" else "Manager-Backup"
        task.setdefault("events", []).append({"at": _now(), "message": f"Fehler: {error}"})
        del task["events"][:-12]
        task.update({
            "status": "failed",
            "stage": "failed",
            "message": f"{noun} konnte nicht erstellt werden.",
            "finished_at": _now(),
            "error": str(error),
            "updated_at": _now(),
        })
        if _current_task_id == task_id:
            _current_task_id = None
        _prune_locked()
        return deepcopy(task)


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        task = _tasks.get(task_id)
        return deepcopy(task) if task is not None else None


def current_task(*, include_last: bool = False) -> dict[str, Any] | None:
    with _lock:
        if _current_task_id:
            task = _tasks.get(_current_task_id)
            if task is not None:
                return deepcopy(task)
        if not include_last or not _tasks:
            return None
        latest = max(_tasks.values(), key=lambda item: item.get("created_at") or "")
        return deepcopy(latest)


def clear_for_tests() -> None:
    global _current_task_id
    with _lock:
        _tasks.clear()
        _current_task_id = None


def _prune_locked() -> None:
    if len(_tasks) <= _MAX_TASKS:
        return
    protected = {_current_task_id} if _current_task_id else set()
    finished = sorted(
        (item for item in _tasks.values() if item.get("id") not in protected and item.get("status") not in {"queued", "running"}),
        key=lambda item: item.get("finished_at") or item.get("created_at") or "",
    )
    for item in finished[: max(0, len(_tasks) - _MAX_TASKS)]:
        _tasks.pop(str(item["id"]), None)
