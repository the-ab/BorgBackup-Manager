from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, BinaryIO

from app.config import RUN_LOG_DIR

_TRUNCATION_MARKER = (
    "\n\n================ PROTOKOLL GEKÜRZT ================\n"
    "Der mittlere Teil wurde wegen der konfigurierten Maximalgröße entfernt.\n"
    "====================================================\n\n"
).encode("utf-8")
_HEAD_BYTES = 64 * 1024
_COMPACT_MARGIN = 1024 * 1024
_DEFAULT_BUFFER_BYTES = 1024 * 1024
_DEFAULT_FLUSH_INTERVAL = 0.75
_DEFAULT_LIVE_DELTA_BYTES = 256 * 1024


def run_log_path(run_id: int) -> Path:
    return RUN_LOG_DIR / f"run-{int(run_id)}.log"


def _compact_run_log(path: Path, max_bytes: int) -> None:
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


class RunLogWriter:
    """Buffered writer for high-volume Borg live logs.

    ``borg create --list`` can emit millions of short lines. Opening, chmod'ing
    and stat'ing the run log for every subprocess chunk consumes substantial CPU
    in the manager. This writer keeps one descriptor open and flushes bounded
    batches so the browser still receives near-live output without per-chunk
    filesystem overhead.
    """

    def __init__(
        self,
        run_id: int,
        max_bytes: int,
        *,
        buffer_bytes: int = _DEFAULT_BUFFER_BYTES,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = run_log_path(run_id)
        self.max_bytes = int(max_bytes)
        self.buffer_bytes = max(4096, int(buffer_bytes))
        self.flush_interval = max(0.0, float(flush_interval))
        self.clock = clock
        self._buffer = bytearray()
        self._handle: BinaryIO | None = None
        self._last_flush = self.clock()
        self._closed = False
        self._written_size = 0
        self._open()

    def _open(self) -> None:
        RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("ab", buffering=1024 * 1024)
        try:
            self._written_size = self.path.stat().st_size
        except OSError:
            self._written_size = 0
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def append(self, text: str) -> None:
        if not text:
            return
        self.append_bytes(text.encode("utf-8", errors="replace"))

    def append_bytes(self, data: bytes | bytearray | memoryview) -> None:
        if self._closed or not data:
            return
        self._buffer.extend(data)
        now = self.clock()
        if len(self._buffer) >= self.buffer_bytes or now - self._last_flush >= self.flush_interval:
            self.flush(now=now)

    def flush(self, *, now: float | None = None) -> None:
        if self._closed or not self._buffer:
            return
        if self._handle is None:
            self._open()
        assert self._handle is not None
        payload_size = len(self._buffer)
        self._handle.write(self._buffer)
        self._handle.flush()
        self._written_size += payload_size
        self._buffer.clear()
        self._last_flush = self.clock() if now is None else now
        if self.max_bytes > 0 and self._written_size > self.max_bytes + _COMPACT_MARGIN:
            self._handle.close()
            self._handle = None
            _compact_run_log(self.path, self.max_bytes)
            self._open()

    def flush_if_due(self) -> bool:
        """Flush pending bytes once the configured live interval has elapsed."""
        if self._closed or not self._buffer:
            return False
        now = self.clock()
        if now - self._last_flush < self.flush_interval:
            return False
        self.flush(now=now)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._closed = True

    def __enter__(self) -> "RunLogWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def append_run_log(run_id: int, text: str, max_bytes: int) -> None:
    if not text:
        return
    with RunLogWriter(run_id, max_bytes, buffer_bytes=4096, flush_interval=0) as writer:
        writer.append(text)


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



def read_run_log_delta(
    run_id: int,
    offset: int = 0,
    max_bytes: int = _DEFAULT_LIVE_DELTA_BYTES,
) -> dict[str, int | bool | str]:
    """Read only newly appended live-log bytes.

    Active dialogs previously re-read and JSON-encoded the same 256 KiB head/tail
    window on every poll. Returning an offset-based delta keeps server and
    browser work proportional to newly emitted Borg output. If compaction or a
    slow client invalidates the offset, the newest bounded tail is returned and
    ``reset`` tells the browser to replace its current view.
    """
    path = run_log_path(run_id)
    limit = max(4096, int(max_bytes))
    try:
        size = path.stat().st_size
    except OSError:
        return {"text": "", "offset": 0, "reset": bool(offset), "truncated": False}

    requested = max(0, int(offset))
    reset = requested > size
    start = 0 if reset else requested
    truncated = False
    if size - start > limit:
        start = max(0, size - limit)
        reset = True
        truncated = True
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            payload = handle.read(limit)
    except OSError:
        return {"text": "", "offset": requested, "reset": False, "truncated": False}
    return {
        "text": payload.decode("utf-8", errors="replace"),
        "offset": start + len(payload),
        "reset": reset,
        "truncated": truncated,
    }

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
