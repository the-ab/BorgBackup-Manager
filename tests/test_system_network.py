from __future__ import annotations

from pathlib import Path

from app import system_network


def test_read_network_totals_aggregates_non_loopback(tmp_path: Path):
    proc = tmp_path / "netdev"
    proc.write_text(
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n"
        "  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
        "  eth1: 3000 0 0 0 0 0 0 0 4000 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    interfaces, rx, tx = system_network._read_network_totals(proc)
    assert interfaces == ["eth0", "eth1"]
    assert rx == 4000
    assert tx == 6000


def test_manager_network_sampler_calculates_rates(monkeypatch):
    samples = iter([
        (["eth0"], 1000, 2000),
        (["eth0"], 3000, 5000),
    ])
    times = iter([10.0, 12.0])
    monkeypatch.setattr(system_network, "_read_network_totals", lambda: next(samples))
    monkeypatch.setattr(system_network.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(system_network, "_previous", None)
    monkeypatch.setattr(system_network, "_last_result", None)
    monkeypatch.setattr(system_network, "_last_sample_at", 0.0)
    first = system_network.sample_manager_network(minimum_interval=0.1)
    second = system_network.sample_manager_network(minimum_interval=0.1)
    assert first["upload_bits_per_second"] is None
    assert second["download_bits_per_second"] == 8000.0
    assert second["upload_bits_per_second"] == 12000.0
