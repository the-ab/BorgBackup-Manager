from __future__ import annotations

import os
from pathlib import Path

from app.config import RUN_LOG_DIR

_TRUNCATION_MARKER = (
    "\n\n================ PROTOKOLL GEKÜRZT ================\n"
    "Der mittlere Teil wurde wegen der konfigurierten Maximalgröße entfernt.\n"
    "====================================================\n\n"
).encode("utf-8")
_HEAD_BYTES = 64 * 1024
_COMPACT_MARGIN = 1024 * 1024


def run_log_path(run_id: int) -> Path:
    return RUN_LOG_DIR / f"run-{int(run_id)}.log"


def append_run_log(run_id: int, text: str, max_bytes: int) -> None:
    if not text:
        return
    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = run_log_path(run_id)
    data = text.encode("utf-8", errors="replace")
    with path.open("ab") as handle:
        handle.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if max_bytes <= 0:
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= max_bytes + _COMPACT_MARGIN:
        return
    head_size = min(_HEAD_BYTES, max_bytes // 4)
    tail_size = max(0, max_bytes - head_size - len(_TRUNCATION_MARKER))
    try:
        with path.open("rb") as handle:
            head = handle.read(head_size)
            if tail_size:
                handle.seek(-tail_size, os.SEEK_END)
                tail = handle.read(tail_size)
            else:
                tail = b""
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            handle.write(head)
            handle.write(_TRUNCATION_MARKER)
            handle.write(tail)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError:
        return


def read_run_log(run_id: int, max_bytes: int | None = None) -> str | None:
    path = run_log_path(run_id)
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
        if max_bytes is None or max_bytes <= 0 or size <= max_bytes:
            return path.read_text(encoding="utf-8", errors="replace")
        head_size = min(_HEAD_BYTES, max_bytes // 4)
        tail_size = max(0, max_bytes - head_size - len(_TRUNCATION_MARKER))
        with path.open("rb") as handle:
            head = handle.read(head_size)
            if tail_size:
                handle.seek(-tail_size, os.SEEK_END)
                tail = handle.read(tail_size)
            else:
                tail = b""
        return (head + _TRUNCATION_MARKER + tail).decode("utf-8", errors="replace")
    except OSError:
        return None


def delete_run_log(run_id: int) -> None:
    try:
        run_log_path(run_id).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def run_log_storage_bytes() -> int:
    if not RUN_LOG_DIR.is_dir():
        return 0
    total = 0
    for path in RUN_LOG_DIR.glob("run-*.log"):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def cleanup_orphan_run_logs(valid_run_ids: set[int]) -> int:
    if not RUN_LOG_DIR.is_dir():
        return 0
    removed = 0
    for path in RUN_LOG_DIR.glob("run-*.log"):
        try:
            run_id = int(path.stem.removeprefix("run-"))
        except ValueError:
            continue
        if run_id in valid_run_ids:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
