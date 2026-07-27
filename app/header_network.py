from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.models import Host
from app.runner import Command, _ssh_argv

_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class InterfaceCounter:
    interface: str
    ip_address: str
    rx_bytes: int
    tx_bytes: int


_lock = Lock()
_previous: dict[str, dict[str, tuple[int, int, float]]] = {}
_last_sample: dict[str, tuple[float, list[dict]]] = {}


def _safe_interface_names(values: list[str] | tuple[str, ...] | None) -> list[str]:
    result: list[str] = []
    for raw in values or []:
        name = str(raw or "").strip().split("@", 1)[0]
        if not name or name == "lo" or not _INTERFACE_RE.fullmatch(name) or name in result:
            continue
        result.append(name)
        if len(result) >= 32:
            break
    return result


def _container_ipv4_addresses() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "up", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    addresses: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        interface = fields[1].split("@", 1)[0]
        address = fields[3].split("/", 1)[0]
        if interface and interface != "lo" and interface not in addresses:
            addresses[interface] = address
    return addresses


def _host_local_ipv4_addresses(
    fib_path: str | Path = "/host/proc/net/fib_trie",
    route_path: str | Path = "/host/proc/net/route",
) -> dict[str, str]:
    try:
        fib_lines = Path(fib_path).read_text(encoding="utf-8", errors="replace").splitlines()
        route_lines = Path(route_path).read_text(encoding="utf-8", errors="replace").splitlines()[1:]
    except OSError:
        return {}
    local_ips: list[ipaddress.IPv4Address] = []
    candidate: str | None = None
    for line in fib_lines:
        match = re.search(r"(?:\+--|\|--)\s+(\d+\.\d+\.\d+\.\d+)(?:/\d+)?", line)
        if match:
            candidate = match.group(1)
        if candidate and "host LOCAL" in line:
            try:
                address = ipaddress.IPv4Address(candidate)
            except ipaddress.AddressValueError:
                candidate = None
                continue
            if not address.is_loopback and not address.is_unspecified and address not in local_ips:
                local_ips.append(address)
            candidate = None
    routes: list[tuple[str, ipaddress.IPv4Address, ipaddress.IPv4Address, int]] = []
    for line in route_lines:
        fields = line.split()
        if len(fields) < 8:
            continue
        interface, destination_hex, mask_hex = fields[0], fields[1], fields[7]
        if interface == "lo":
            continue
        try:
            destination = ipaddress.IPv4Address(int.from_bytes(bytes.fromhex(destination_hex), "little"))
            mask = ipaddress.IPv4Address(int.from_bytes(bytes.fromhex(mask_hex), "little"))
            mask_int = int(mask)
            prefix = mask_int.bit_count()
        except (ValueError, ipaddress.AddressValueError):
            continue
        if prefix <= 0:
            continue
        routes.append((interface, destination, mask, prefix))
    result: dict[str, str] = {}
    best_prefix: dict[str, int] = {}
    for address in local_ips:
        address_int = int(address)
        for interface, destination, mask, prefix in routes:
            if address_int & int(mask) != int(destination):
                continue
            if prefix > best_prefix.get(interface, -1):
                result[interface] = str(address)
                best_prefix[interface] = prefix
    return result


def _counter_root_and_addresses() -> tuple[Path, dict[str, str], str]:
    host_root = Path("/host/sys/class/net")
    if host_root.is_dir():
        return host_root, _host_local_ipv4_addresses(), "host"
    return Path("/sys/class/net"), _container_ipv4_addresses(), "container"


def _local_counters(selected: list[str] | None = None, *, maximum: int = 3) -> tuple[list[InterfaceCounter], str]:
    root, addresses, scope = _counter_root_and_addresses()
    requested = _safe_interface_names(selected)
    if requested:
        names = requested
    else:
        names = list(addresses)
        try:
            fallback = sorted(path.name for path in root.iterdir() if path.name != "lo")
        except OSError:
            fallback = []
        names.extend(name for name in fallback if name not in names)
    counters: list[InterfaceCounter] = []
    for interface in names:
        if len(counters) >= max(1, min(32, int(maximum))):
            break
        try:
            rx = int((root / interface / "statistics/rx_bytes").read_text().strip())
            tx = int((root / interface / "statistics/tx_bytes").read_text().strip())
        except (OSError, ValueError):
            continue
        counters.append(InterfaceCounter(interface, addresses.get(interface, ""), rx, tx))
    return counters, scope


_REMOTE_SCRIPT = r'''set +e
bbm_max="$1"
shift
case "$bbm_max" in *[!0-9]*|'') bbm_max=3 ;; esac
[ "$bbm_max" -ge 1 ] 2>/dev/null || bbm_max=3
[ "$bbm_max" -le 32 ] 2>/dev/null || bbm_max=32
command -v ip >/dev/null 2>&1 || exit 0
bbm_emit() {
  bbm_iface="${1%%@*}"
  [ -n "$bbm_iface" ] && [ "$bbm_iface" != "lo" ] || return 0
  bbm_rx_file="/sys/class/net/$bbm_iface/statistics/rx_bytes"
  bbm_tx_file="/sys/class/net/$bbm_iface/statistics/tx_bytes"
  [ -r "$bbm_rx_file" ] && [ -r "$bbm_tx_file" ] || return 0
  bbm_ip="$(ip -o -4 addr show dev "$bbm_iface" scope global 2>/dev/null | awk 'NR==1 { split($4,a,"/"); print a[1] }')"
  IFS= read -r bbm_rx < "$bbm_rx_file" || return 0
  IFS= read -r bbm_tx < "$bbm_tx_file" || return 0
  printf 'BBMHEADERNET\t%s\t%s\t%s\t%s\n' "$bbm_iface" "${bbm_ip:--}" "$bbm_rx" "$bbm_tx"
}
if [ "$#" -gt 0 ]; then
  bbm_count=0
  for bbm_requested in "$@"; do
    [ "$bbm_count" -lt "$bbm_max" ] || break
    bbm_before="$bbm_count"
    bbm_line="$(bbm_emit "$bbm_requested")"
    if [ -n "$bbm_line" ]; then
      printf '%s\n' "$bbm_line"
      bbm_count=$((bbm_count + 1))
    fi
  done
  exit 0
fi
command -v awk >/dev/null 2>&1 || exit 0
ip -o -4 addr show up scope global 2>/dev/null |
  awk '!seen[$2]++ { iface=$2; sub(/@.*/, "", iface); print iface }' |
  while IFS= read -r bbm_iface; do bbm_emit "$bbm_iface"; done |
  head -n "$bbm_max"
'''


def _materialize_command(command: Command) -> tuple[list[str], tempfile.TemporaryDirectory[str] | None]:
    argv = list(command.argv)
    directory: tempfile.TemporaryDirectory[str] | None = None
    if not command.temp_files:
        return argv, directory
    directory = tempfile.TemporaryDirectory(prefix="bbm-header-network-")
    root = Path(directory.name)
    replacements: dict[str, str] = {}
    for index, (placeholder, content) in enumerate(command.temp_files.items(), start=1):
        path = root / f"secret-{index}"
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o600)
        replacements[placeholder] = str(path)
    resolved: list[str] = []
    for argument in argv:
        for placeholder, path in replacements.items():
            argument = argument.replace(placeholder, path)
        resolved.append(argument)
    return resolved, directory


def _remote_counters(host: Host, selected: list[str] | None = None, *, maximum: int = 3) -> list[InterfaceCounter]:
    names = _safe_interface_names(selected)
    command = _ssh_argv(host, ["sh", "-c", _REMOTE_SCRIPT, "--", str(max(1, min(32, maximum))), *names], {})
    argv, directory = _materialize_command(command)
    try:
        result = subprocess.run(
            argv,
            input=command.stdin_data,
            capture_output=True,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Netzwerkabfrage des Geräts hat das Zeitlimit überschritten") from exc
    except OSError as exc:
        raise RuntimeError(f"Netzwerkabfrage konnte nicht gestartet werden: {exc}") from exc
    finally:
        if directory is not None:
            directory.cleanup()
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-1000:]
        raise RuntimeError(detail or f"SSH-Netzwerkabfrage fehlgeschlagen (RC {result.returncode})")
    counters: list[InterfaceCounter] = []
    for raw in result.stdout.decode("utf-8", errors="replace").splitlines():
        if not raw.startswith("BBMHEADERNET\t"):
            continue
        fields = raw.split("\t")
        if len(fields) != 5:
            continue
        interface, ip_address = fields[1], fields[2]
        try:
            rx, tx = int(fields[3]), int(fields[4])
        except ValueError:
            continue
        if interface == "lo" or not _INTERFACE_RE.fullmatch(interface):
            continue
        counters.append(InterfaceCounter(interface, "" if ip_address == "-" else ip_address, rx, tx))
        if len(counters) >= max(1, min(32, maximum)):
            break
    return counters


def discover_interfaces(*, host: Host | None = None) -> list[dict]:
    if host is not None:
        counters = _remote_counters(host, maximum=32)
        scope = "host"
    else:
        counters, scope = _local_counters(maximum=32)
    return [{"interface": item.interface, "ip_address": item.ip_address, "scope": scope} for item in counters]


def sample_interfaces(
    *,
    sample_key: str,
    host: Host | None = None,
    selected: list[str] | None = None,
    maximum: int = 3,
    minimum_interval: float = 0.75,
) -> list[dict]:
    now = time.monotonic()
    with _lock:
        cached = _last_sample.get(sample_key)
        if cached is not None and now - cached[0] < max(0.2, minimum_interval):
            return [dict(item) for item in cached[1]]

    if host is not None:
        counters = _remote_counters(host, selected, maximum=maximum)
        scope = "host"
    else:
        counters, scope = _local_counters(selected, maximum=maximum)
    sampled_at = time.monotonic()
    with _lock:
        previous = _previous.setdefault(sample_key, {})
        result: list[dict] = []
        current_names: set[str] = set()
        for item in counters:
            current_names.add(item.interface)
            download = upload = None
            old = previous.get(item.interface)
            if old is not None:
                old_rx, old_tx, old_at = old
                delta = sampled_at - old_at
                if delta > 0 and item.rx_bytes >= old_rx and item.tx_bytes >= old_tx:
                    download = ((item.rx_bytes - old_rx) * 8.0) / delta
                    upload = ((item.tx_bytes - old_tx) * 8.0) / delta
            previous[item.interface] = (item.rx_bytes, item.tx_bytes, sampled_at)
            result.append({
                "interface": item.interface,
                "ip_address": item.ip_address,
                "download_bits_per_second": download,
                "upload_bits_per_second": upload,
                "scope": scope,
            })
        for stale in set(previous) - current_names:
            previous.pop(stale, None)
        _last_sample[sample_key] = (sampled_at, result)
        return [dict(item) for item in result]
