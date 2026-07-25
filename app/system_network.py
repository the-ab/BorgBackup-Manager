from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class ManagerNetworkActivity:
    interface: str
    download_bits_per_second: float | None
    upload_bits_per_second: float | None


_lock = Lock()
_previous: tuple[int, int, float] | None = None
_last_result: ManagerNetworkActivity | None = None
_last_sample_at = 0.0


def _read_network_totals(path: str | Path = "/proc/net/dev") -> tuple[list[str], int, int] | None:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[2:]
    except OSError:
        return None
    interfaces: list[str] = []
    rx_total = 0
    tx_total = 0
    for line in lines:
        if ":" not in line:
            continue
        name, payload = line.split(":", 1)
        interface = name.strip()
        if not interface or interface == "lo":
            continue
        fields = payload.split()
        if len(fields) < 9:
            continue
        try:
            rx = int(fields[0])
            tx = int(fields[8])
        except ValueError:
            continue
        interfaces.append(interface)
        rx_total += rx
        tx_total += tx
    if not interfaces:
        return None
    return sorted(interfaces), rx_total, tx_total


def sample_manager_network(*, minimum_interval: float = 0.5) -> dict | None:
    """Return aggregate non-loopback container network rates.

    The live run endpoint may be polled by more than one browser. Very closely
    spaced calls reuse the last sample so one browser cannot make another one's
    rate interval collapse to a few milliseconds.
    """
    global _previous, _last_result, _last_sample_at
    now = time.monotonic()
    with _lock:
        if _last_result is not None and now - _last_sample_at < max(0.1, minimum_interval):
            return asdict(_last_result)
        current = _read_network_totals()
        if current is None:
            return None
        interfaces, rx, tx = current
        download = upload = None
        if _previous is not None:
            prev_rx, prev_tx, prev_at = _previous
            delta = now - prev_at
            if delta > 0 and rx >= prev_rx and tx >= prev_tx:
                download = ((rx - prev_rx) * 8.0) / delta
                upload = ((tx - prev_tx) * 8.0) / delta
        _previous = (rx, tx, now)
        _last_sample_at = now
        _last_result = ManagerNetworkActivity(
            interface="+".join(interfaces),
            download_bits_per_second=download,
            upload_bits_per_second=upload,
        )
        return asdict(_last_result)
