from __future__ import annotations

from pathlib import Path

from app import run_logs


PROJECT_ROOT = Path(__file__).parents[1]


def test_file_log_keeps_start_and_end_when_compacted(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    run_logs.append_run_log(42, "HEADER\n", 1024 * 1024)
    for index in range(8):
        run_logs.append_run_log(42, (f"BLOCK-{index}\n" + "x" * 300_000 + "\n"), 1024 * 1024)
    run_logs.append_run_log(42, "FINAL STATS\n", 1024 * 1024)

    content = run_logs.read_run_log(42)
    assert content is not None
    assert content.startswith("HEADER")
    assert "PROTOKOLL GEKÜRZT" in content
    assert content.endswith("FINAL STATS\n")
    assert run_logs.run_log_path(42).stat().st_size <= 2 * 1024 * 1024 + 4096


def test_read_view_can_limit_large_log(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    run_logs.append_run_log(7, "START\n" + "a" * 600_000 + "\nEND\n", 10 * 1024 * 1024)
    content = run_logs.read_run_log(7, 256 * 1024)
    assert content is not None
    assert content.startswith("START")
    assert "PROTOKOLL GEKÜRZT" in content
    assert content.endswith("END\n")


def test_legacy_database_payload_is_migrated_to_file_and_truncated(monkeypatch, tmp_path):
    from app import main as main_module
    from app.database import Base, SessionLocal, engine
    from app.models import Run

    Base.metadata.create_all(engine)
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(main_module, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(main_module, "run_log_path", lambda run_id: tmp_path / f"run-{run_id}.log")
    monkeypatch.setattr(main_module, "append_run_log", lambda run_id, text, _max: (tmp_path / f"run-{run_id}.log").write_text(text, encoding="utf-8"))
    payload = "START\nA srv/data/normal.txt\nC var/lib/app/live.db\n" + ("x" * 100_000) + "\nEND\n"
    with SessionLocal() as db:
        row = Run(action="backup", status="warning", output=payload, error=payload, log_output=payload)
        db.add(row)
        db.commit()
        run_id = row.id

    assert main_module.migrate_run_payloads_to_files() >= 1
    assert (tmp_path / f"run-{run_id}.log").read_text(encoding="utf-8") == payload
    with SessionLocal() as db:
        row = db.get(Run, run_id)
        assert len(row.output.encode()) <= 4 * 1024
        assert len(row.error.encode()) <= 8 * 1024
        assert len(row.log_output.encode()) <= 16 * 1024
        assert "srv/data/normal.txt" not in row.output
        assert "srv/data/normal.txt" not in row.log_output
        assert "var/lib/app/live.db" not in row.error
        assert "var/lib/app/live.db" not in row.log_output
        assert "var/lib/app/live.db" in row.warning_summary_json


def test_high_volume_writer_batches_filesystem_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    now = [0.0]
    writer = run_logs.RunLogWriter(
        99,
        10 * 1024 * 1024,
        buffer_bytes=1024,
        flush_interval=0.25,
        clock=lambda: now[0],
    )

    writer.append("A" * 400)
    assert run_logs.run_log_path(99).stat().st_size == 0
    writer.append("B" * 400)
    assert run_logs.run_log_path(99).stat().st_size == 0

    now[0] = 0.3
    writer.append("C")
    assert run_logs.run_log_path(99).read_text(encoding="utf-8") == "A" * 400 + "B" * 400 + "C"

    writer.append("FINAL")
    writer.close()
    assert run_logs.read_run_log(99).endswith("FINAL")


def test_live_delta_returns_only_new_bytes_and_tracks_offset(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    run_logs.append_run_log(123, "first\n", 10 * 1024 * 1024)

    first = run_logs.read_run_log_delta(123, 0, 4096)
    assert first["text"] == "first\n"
    assert first["offset"] == len(b"first\n")
    assert first["reset"] is False

    run_logs.append_run_log(123, "second\n", 10 * 1024 * 1024)
    second = run_logs.read_run_log_delta(123, int(first["offset"]), 4096)
    assert second["text"] == "second\n"
    assert second["offset"] == len(b"first\nsecond\n")
    assert second["reset"] is False


def test_live_delta_resets_to_bounded_tail_when_client_falls_behind(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    payload = ("line\n" * 5000).encode()
    path = run_logs.run_log_path(124)
    path.write_bytes(payload)

    delta = run_logs.read_run_log_delta(124, 0, 4096)
    assert delta["reset"] is True
    assert delta["truncated"] is True
    assert len(str(delta["text"]).encode()) <= 4096
    assert delta["offset"] == len(payload)


def test_backup_stream_is_file_backed_without_temporary_sqlite_path_mirroring():
    service = (PROJECT_ROOT / "app/service.py").read_text(encoding="utf-8")

    assert "class _BackupSqlitePreviewFilter" in service
    assert "_SQLITE_ONLY_BORG_ITEM_BLOCK_BYTES_RE.fullmatch" in service
    assert "if stream == \"stdout\" and backup_preview_filter is not None" in service
    assert "clean_source = output if action == \"backup\"" in service


def test_sparse_writer_can_flush_due_without_new_append(monkeypatch, tmp_path):
    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    now = [0.0]
    writer = run_logs.RunLogWriter(150, 1024 * 1024, buffer_bytes=1024 * 1024, flush_interval=0.75, clock=lambda: now[0])
    writer.append("HEADER\n")
    assert run_logs.run_log_path(150).stat().st_size == 0
    now[0] = 0.8
    assert writer.flush_if_due() is True
    assert run_logs.run_log_path(150).read_text(encoding="utf-8") == "HEADER\n"
    assert writer.flush_if_due() is False
    writer.close()


def test_service_runs_time_driven_live_log_flush():
    service = (PROJECT_ROOT / "app/service.py").read_text(encoding="utf-8")
    assert "async def flush_live_log_periodically" in service
    assert "log_writer.flush_if_due()" in service
    assert "live_log_flush_task.cancel()" in service
