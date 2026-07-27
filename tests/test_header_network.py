from __future__ import annotations

from pathlib import Path

from app import header_network
from app.header_network import InterfaceCounter
from app.schemas import SettingsIn


def test_header_network_settings_defaults_are_safe_and_disabled():
    settings = SettingsIn()
    assert settings.header_network_enabled is False
    assert settings.header_network_source == "manager"
    assert settings.header_network_host_id is None
    assert settings.header_network_interfaces == []
    assert settings.header_network_max_interfaces == 3
    assert settings.header_network_interval_seconds == 5


def test_header_network_interface_validation_deduplicates_and_limits():
    settings = SettingsIn(header_network_interfaces=["eth0", "eth0", "bond0", "vlan.20"])
    assert settings.header_network_interfaces == ["eth0", "bond0", "vlan.20"]


def test_header_network_sampler_calculates_individual_rates(monkeypatch):
    samples = iter([
        ([InterfaceCounter("eth0", "192.0.2.10", 1000, 2000)], "host"),
        ([InterfaceCounter("eth0", "192.0.2.10", 3000, 5000)], "host"),
    ])
    times = iter([10.0, 10.0, 12.0, 12.0])
    monkeypatch.setattr(header_network, "_local_counters", lambda selected=None, maximum=3: next(samples))
    monkeypatch.setattr(header_network.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(header_network, "_previous", {})
    monkeypatch.setattr(header_network, "_last_sample", {})

    first = header_network.sample_interfaces(sample_key="manager", minimum_interval=0.1)
    second = header_network.sample_interfaces(sample_key="manager", minimum_interval=0.1)

    assert first[0]["download_bits_per_second"] is None
    assert first[0]["scope"] == "host"
    assert second[0]["download_bits_per_second"] == 8000.0
    assert second[0]["upload_bits_per_second"] == 12000.0
    assert second[0]["ip_address"] == "192.0.2.10"


def test_host_ipv4_mapping_uses_host_proc_routes(tmp_path: Path):
    fib = tmp_path / "fib_trie"
    route = tmp_path / "route"
    fib.write_text(
        "Main:\n"
        "  +-- 192.168.178.0/24\n"
        "     +-- 192.168.178.25/32\n"
        "        /32 host LOCAL\n",
        encoding="utf-8",
    )
    route.write_text(
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "enp3s0\t00B2A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n",
        encoding="utf-8",
    )
    assert header_network._host_local_ipv4_addresses(fib, route) == {"enp3s0": "192.168.178.25"}


def test_header_network_ui_contains_persistent_monitor_and_settings():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    js = (root / "app/static/app.js").read_text(encoding="utf-8")
    css = (root / "app/static/style.css").read_text(encoding="utf-8")
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    assert 'id="header-network-monitor"' in html
    assert 'name="header_network_source"' in html
    assert 'name="header_network_host_id"' in html
    assert 'data-header-network-interface' in js
    assert 'scheduleHeaderNetworkPoll' in js
    assert '@media (max-width: 760px)' in css and '.header-network-monitor' in css
    assert '/sys:/host/sys:ro' in compose
    assert '/proc/net:/host/proc/net:ro' in compose
