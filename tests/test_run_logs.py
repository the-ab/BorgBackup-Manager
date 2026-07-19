from __future__ import annotations

from app import run_logs


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
    from app.database import SessionLocal
    from app.models import Run

    monkeypatch.setattr(run_logs, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(main_module, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(main_module, "run_log_path", lambda run_id: tmp_path / f"run-{run_id}.log")
    monkeypatch.setattr(main_module, "append_run_log", lambda run_id, text, _max: (tmp_path / f"run-{run_id}.log").write_text(text, encoding="utf-8"))
    payload = "START\n" + ("x" * 100_000) + "\nEND\n"
    with SessionLocal() as db:
        row = Run(action="backup", status="success", output=payload, error=payload, log_output=payload)
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
