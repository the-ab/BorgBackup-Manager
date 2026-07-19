from __future__ import annotations

import json
import os
from threading import Lock

from app.config import SETTINGS_PATH
from app.schemas import SettingsIn


_lock = Lock()


def _environment_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def _environment_percent(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if 1 <= value <= 100 else default


def default_settings() -> SettingsIn:
    return SettingsIn(
        appearance=os.getenv("BBM_APPEARANCE", "auto"),
        max_parallel_runs=_environment_limit("BBM_MAX_PARALLEL_RUNS", 0, 0, 64),
        repository_size_after_run=os.getenv("BBM_REPOSITORY_SIZE_AFTER_RUN", "1").lower()
        not in {"0", "false", "no"},
        storage_guard_enabled=os.getenv("BBM_STORAGE_GUARD_ENABLED", "1").lower()
        not in {"0", "false", "no"},
        storage_guard_threshold_percent=_environment_percent("BBM_STORAGE_GUARD_THRESHOLD_PERCENT", 95),
    )


def load_settings() -> SettingsIn:
    defaults = default_settings().model_dump()
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")) if SETTINGS_PATH.is_file() else {}
        if isinstance(raw, dict):
            defaults.update({key: value for key, value in raw.items() if key in defaults})
    except (OSError, ValueError, TypeError):
        pass
    try:
        return SettingsIn.model_validate(defaults)
    except ValueError:
        return default_settings()


def save_settings(settings: SettingsIn) -> SettingsIn:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        temporary = SETTINGS_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(settings.model_dump(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(SETTINGS_PATH)
    return settings
