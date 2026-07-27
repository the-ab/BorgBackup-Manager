from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import service


class _Log:
    def __init__(self):
        self.lines: list[str] = []

    def append(self, text: str) -> None:
        self.lines.append(text)


def test_external_storage_monitor_trips_guard_when_threshold_is_reached(monkeypatch):
    values = iter([
        {"percent": 94.0, "path": "./repo", "mount_point": "/home/backup"},
        {"percent": 95.0, "path": "./repo", "mount_point": "/home/backup"},
    ])

    async def fake_refresh(_repository_id: int):
        return next(values)

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(service, "refresh_external_repository_storage", fake_refresh)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    async def scenario():
        event = asyncio.Event()
        state: dict[str, str] = {}
        log = _Log()
        await service._monitor_external_repository_storage(
            7, 11, event, state, log, guard_enabled=True, threshold=95,
        )
        return event, state, log

    event, state, log = asyncio.run(scenario())
    assert event.is_set()
    assert "95.0%" in state["reason"]
    assert "95%-Speicherplatz-Sperre" in state["reason"]
    assert any("Borg wird kontrolliert gestoppt" in line for line in log.lines)


def test_external_storage_monitor_fails_safe_after_two_probe_failures(monkeypatch):
    attempts = 0

    async def fake_refresh(_repository_id: int):
        nonlocal attempts
        attempts += 1
        raise ValueError("df nicht erlaubt")

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(service, "refresh_external_repository_storage", fake_refresh)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    async def scenario():
        event = asyncio.Event()
        state: dict[str, str] = {}
        log = _Log()
        await service._monitor_external_repository_storage(
            8, 12, event, state, log, guard_enabled=True, threshold=90,
        )
        return event, state, log

    event, state, log = asyncio.run(scenario())
    assert attempts == service.EXTERNAL_STORAGE_MAX_CONSECUTIVE_FAILURES == 2
    assert event.is_set()
    assert "2-mal hintereinander" in state["reason"]
    assert "df nicht erlaubt" in state["reason"]
    assert any("SPEICHERPLATZ-SPERRE" in line for line in log.lines)


def test_external_storage_monitor_does_not_abort_if_guard_is_disabled(monkeypatch):
    calls = 0

    async def fake_refresh(_repository_id: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"percent": 99.0, "path": "./repo", "mount_point": "/home/backup"}
        raise asyncio.CancelledError

    async def fake_sleep(_seconds: float):
        if calls:
            raise asyncio.CancelledError
        return None

    monkeypatch.setattr(service, "refresh_external_repository_storage", fake_refresh)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)

    async def scenario():
        event = asyncio.Event()
        state: dict[str, str] = {}
        log = _Log()
        task = asyncio.create_task(service._monitor_external_repository_storage(
            9, 13, event, state, log, guard_enabled=False, threshold=95,
        ))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return event, state

    event, state = asyncio.run(scenario())
    assert not event.is_set()
    assert state == {}


def test_external_storage_log_size_formatter_uses_mb_gb_tb_ranges():
    assert service.format_external_storage_bytes(512 * 1024) == "512.0 KB"
    assert service.format_external_storage_bytes(512 * 1024**2) == "512.0 MB"
    assert service.format_external_storage_bytes(1024**3 - 1).endswith(" MB")
    assert service.format_external_storage_bytes(500 * 1024**3) == "500.0 GB"
    assert service.format_external_storage_bytes(1024**4 - 1).endswith(" GB")
    assert service.format_external_storage_bytes(2 * 1024**4) == "2.00 TB"
    assert service.format_external_storage_bytes(534_925_803_520) == "498.2 GB"
