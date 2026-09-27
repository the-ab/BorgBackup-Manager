from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from app import backups, header_network
from app.header_network import InterfaceCounter


@pytest.mark.parametrize("failure", ["copy", "replace"])
def test_restore_failure_keeps_original_components_and_sqlite_sidecars(tmp_path, monkeypatch, failure):
    data = tmp_path / "data"
    staging = tmp_path / "staging"
    data.mkdir()
    (staging / "data" / "security").mkdir(parents=True)
    original = {"manager.db": "old-db", "manager.db-wal": "old-wal",
                "manager.db-shm": "old-shm", "notifications.json": "old-notifications",
                "security/master.key": "old-key"}
    for name, value in original.items():
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)
    (staging / "data" / "manager.db").write_text("new-db")
    (staging / "data" / "security" / "master.key").write_text("new-key")
    monkeypatch.setattr(backups, "DATA_DIR", data)
    if failure == "copy":
        copytree = backups.shutil.copytree
        def fail_copy(source, target, *args, **kwargs):
            if Path(source) == staging / "data" / "security":
                raise OSError("simulated full disk")
            return copytree(source, target, *args, **kwargs)
        monkeypatch.setattr(backups.shutil, "copytree", fail_copy)
    else:
        replace = Path.replace
        failed = False
        def fail_replace(source, target):
            nonlocal failed
            if Path(target) == data / "security" and not failed:
                failed = True
                raise OSError("simulated rename failure")
            return replace(source, target)
        monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        backups.apply_prepared_restore(staging)
    for name, value in original.items():
        assert (data / name).read_text() == value
    assert staging.is_dir()


@pytest.mark.parametrize("fail", [False, True])
def test_parallel_network_samples_share_one_query_and_error(monkeypatch, fail):
    started, waiting = Event(), Event()
    class ObservedFuture(Future):
        def result(self, timeout=None):
            waiting.set()
            return super().result(timeout)
    monkeypatch.setattr(header_network, "Future", ObservedFuture, raising=False)
    monkeypatch.setattr(header_network, "_last_sample", {})
    monkeypatch.setattr(header_network, "_previous", {})
    count = 0
    def query(selected=None, maximum=3):
        nonlocal count
        count += 1
        started.set()
        assert waiting.wait(3)
        if fail:
            raise RuntimeError("probe failed")
        return [InterfaceCounter("eth0", "", 1, 1)], "host"
    monkeypatch.setattr(header_network, "_local_counters", query)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(header_network.sample_interfaces, sample_key="quality-parallel")
        assert started.wait(3)
        second = pool.submit(header_network.sample_interfaces, sample_key="quality-parallel")
        if fail:
            for future in (first, second):
                with pytest.raises(RuntimeError, match="probe failed"):
                    future.result(5)
        else:
            assert first.result(5) == second.result(5)
    assert count == 1
    # A failed in-flight request must not poison subsequent sampling.
    monkeypatch.setattr(header_network, "_local_counters",
                        lambda *args, **kwargs: ([InterfaceCounter("eth1", "", 1, 1)], "host"))
    if fail:
        assert header_network.sample_interfaces(sample_key="quality-parallel")[0]["interface"] == "eth1"


def test_network_selection_change_invalidates_cached_sample(monkeypatch):
    monkeypatch.setattr(header_network, "_last_sample", {})
    monkeypatch.setattr(header_network, "_previous", {})
    monkeypatch.setattr(header_network, "_local_counters",
                        lambda selected=None, maximum=3:
                        ([InterfaceCounter(selected[0], "", 1, 1)], "host"))
    assert header_network.sample_interfaces(sample_key="selection", selected=["eth0"])[0]["interface"] == "eth0"
    assert header_network.sample_interfaces(sample_key="selection", selected=["eth1"])[0]["interface"] == "eth1"


@pytest.mark.asyncio
async def test_slow_borg_diagnostic_does_not_run_on_event_loop(monkeypatch):
    from app import main
    loop_thread = get_ident()
    calls = []
    class StopAfterVersion(Exception):
        pass
    def probe(*args, **kwargs):
        calls.append(get_ident())
        return SimpleNamespace(stdout="borg 1.4.0", returncode=0)
    monkeypatch.setattr(main.subprocess, "run", probe)
    monkeypatch.setattr(main, "load_settings", lambda: (_ for _ in ()).throw(StopAfterVersion()))
    with pytest.raises(StopAfterVersion):
        await main.system_diagnostics()
    assert calls and all(thread != loop_thread for thread in calls)

@pytest.mark.parametrize("boundary", range(1, 9))
def test_restore_rollback_at_every_exchange_boundary(monkeypatch, tmp_path, boundary):
    data, staging = tmp_path / "live", tmp_path / "stage"
    data.mkdir()
    (staging / "data" / "security").mkdir(parents=True)
    original = {"manager.db": "old", "manager.db-wal": "wal", "manager.db-shm": "shm",
                "notifications.json": "settings", "security/master.key": "key"}
    for name, value in original.items():
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    (staging / "data" / "manager.db").write_text("new")
    (staging / "data" / "security" / "master.key").write_text("new-key")
    monkeypatch.setattr(backups, "DATA_DIR", data)
    original_replace = Path.replace
    calls = 0
    def replace(source, target):
        nonlocal calls
        calls += 1
        if calls == boundary:
            raise OSError("exchange boundary")
        return original_replace(source, target)
    monkeypatch.setattr(Path, "replace", replace)
    # manager old/new, notification removal, security old/new, WAL, SHM = 7.
    if boundary <= 7:
        with pytest.raises(OSError):
            backups.apply_prepared_restore(staging)
        for name, value in original.items():
            assert (data / name).read_text() == value
    else:
        backups.apply_prepared_restore(staging)
        assert (data / "manager.db").read_text() == "new"
        assert (data / "security" / "master.key").read_text() == "new-key"
        assert not (data / "notifications.json").exists()


def test_network_sources_do_not_block_each_other(monkeypatch):
    entered, release = Event(), Event()
    monkeypatch.setattr(header_network, "_last_sample", {})
    monkeypatch.setattr(header_network, "_previous", {})
    def query(selected=None, maximum=3):
        if selected == ["slow"]:
            entered.set()
            assert release.wait(3)
        return [InterfaceCounter(selected[0], "", 1, 1)], "host"
    monkeypatch.setattr(header_network, "_local_counters", query)
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(header_network.sample_interfaces, sample_key="slow", selected=["slow"])
        assert entered.wait(3)
        try:
            fast = pool.submit(header_network.sample_interfaces, sample_key="fast", selected=["fast"])
            assert fast.result(1)[0]["interface"] == "fast"
        finally:
            release.set()
        assert slow.result(3)[0]["interface"] == "slow"

def test_failed_restore_rollback_retains_original_files(monkeypatch, tmp_path):
    data, staging = tmp_path / "data", tmp_path / "staging"
    data.mkdir()
    (staging / "data" / "security").mkdir(parents=True)
    (data / "manager.db").write_text("original")
    (staging / "data" / "manager.db").write_text("replacement")
    (staging / "data" / "security" / "master.key").write_text("test-key")
    monkeypatch.setattr(backups, "DATA_DIR", data)
    replace = Path.replace
    def fail(source, target):
        if Path(target) == data / "security" or (source.parent.name == "old" and source.name == "manager.db"):
            raise OSError("persistent filesystem failure")
        return replace(source, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(RuntimeError, match="Originaldateien"):
        backups.apply_prepared_restore(staging)
    originals = list(data.glob(".restore-transaction-*/old/manager.db"))
    assert len(originals) == 1
    assert originals[0].read_text() == "original"
    assert originals[0].parent.parent.stat().st_mode & 0o077 == 0


def test_audit_missing_file_reports_error_without_traceback(tmp_path):
    import runpy
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/project-audit.py"))
    root = namespace["ROOT"]
    missing = root / "deliberately-missing-quality-test-file"
    assert not missing.exists()
    assert namespace["_read"](missing) == ""
    assert any("deliberately-missing-quality-test-file" in error for error in namespace["ERRORS"])
