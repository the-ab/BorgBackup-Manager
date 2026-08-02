from __future__ import annotations

import json

from app.borg_progress import (
    BorgRestoreProgressStreamFilter,
    clear_run_restore_progress,
    get_run_restore_progress,
    set_run_restore_progress,
)


def _json_line(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def test_restore_progress_control_records_are_chunk_safe():
    parser = BorgRestoreProgressStreamFilter()
    first, progress = parser.feed(b"\x1eBBMREST")
    assert first == b""
    assert progress is None

    output, progress = parser.feed(b"ORE\tPREPARING\n\x1eBBMRESTORE\tBASELINE\t12\t4096\n")
    assert b"RESTORE-VORBEREITUNG" in output
    assert b"RESTORE-BASIS" in output
    assert progress is not None
    assert progress.phase == "preparing"
    assert progress.total_files == 12
    assert progress.total_bytes == 4096


def test_restore_progress_parses_bytes_items_path_and_success(monkeypatch):
    ticks = iter([10.0, 10.0, 11.0, 12.0, 13.0, 14.0])
    monkeypatch.setattr("app.borg_progress.time.monotonic", lambda: next(ticks))
    parser = BorgRestoreProgressStreamFilter()
    parser.feed(b"\x1eBBMRESTORE\tBASELINE\t2\t1000\n")
    parser.feed(b"\x1eBBMRESTORE\tRESTORING\n")

    filtered, progress = parser.feed(_json_line({
        "type": "progress_percent", "msgid": "extract",
        "current": 500, "total": 1000, "info": ["home/user/a"], "finished": False,
    }))
    assert filtered == b""
    assert progress is not None
    assert progress.processed_bytes == 500
    assert progress.total_bytes == 1000
    assert progress.path == "home/user/a"
    assert progress.percent == 50.0
    assert progress.bytes_per_second > 0
    assert progress.eta_seconds is not None

    filtered, progress = parser.feed(_json_line({
        "type": "log_message", "name": "borg.output.list", "message": "home/user/a",
    }))
    assert filtered == b"home/user/a\n"
    assert progress is not None
    assert progress.processed_files == 1

    parser.feed(_json_line({
        "type": "log_message", "name": "borg.output.list", "message": "home/user/b",
    }))
    filtered, progress = parser.feed(b"\x1eBBMRESTORE\tFINISHED\t0\n")
    assert filtered == b""
    assert progress is not None
    assert progress.phase == "finished"
    assert progress.processed_bytes == 1000
    assert progress.processed_files == 2
    assert progress.percent == 100.0
    assert progress.eta_seconds == 0


def test_restore_progress_keeps_borg_warning_readable_and_marks_failure():
    parser = BorgRestoreProgressStreamFilter()
    warning = _json_line({
        "type": "log_message", "name": "borg.output.error", "message": "restore warning",
    })
    filtered, progress = parser.feed(warning)
    assert filtered == b"restore warning\n"
    assert progress is None

    _, progress = parser.feed(b"\x1eBBMRESTORE\tFINISHED\t2\n")
    assert progress is not None
    assert progress.phase == "failed"


def test_restore_progress_live_store_round_trip():
    parser = BorgRestoreProgressStreamFilter()
    _, progress = parser.feed(b"\x1eBBMRESTORE\tBASELINE\t3\t2048\n")
    assert progress is not None
    set_run_restore_progress(91, progress)
    stored = get_run_restore_progress(91)
    assert stored is not None
    assert stored["total_files"] == 3
    assert stored["total_bytes"] == 2048
    clear_run_restore_progress(91)
    assert get_run_restore_progress(91) is None


def test_restore_live_progress_is_rendered_in_run_dialog():
    from pathlib import Path

    javascript = (Path(__file__).resolve().parents[1] / "app/static/app.js").read_text(encoding="utf-8")
    assert "function renderRestoreProgress" in javascript
    assert "run.restore_progress" in javascript
    assert "Verarbeitete Größe" in javascript
    assert "Verbleibende Größe" in javascript
    assert "Restzeitschätzung" in javascript
