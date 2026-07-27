from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from threading import Lock

_PROGRESS_RE = re.compile(
    rb"^\s*"
    rb"(?P<original>[0-9]+(?:[.,][0-9]+)?)\s+(?P<original_unit>[kKMGTPE]?i?B)\s+O\s+"
    rb"(?P<compressed>[0-9]+(?:[.,][0-9]+)?)\s+(?P<compressed_unit>[kKMGTPE]?i?B)\s+C\s+"
    rb"(?P<deduplicated>[0-9]+(?:[.,][0-9]+)?)\s+(?P<deduplicated_unit>[kKMGTPE]?i?B)\s+D\s+"
    rb"(?P<files>[0-9]+)\s+N(?:\s+(?P<path>.*?))?\s*$"
)

_DECIMAL_UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "PB": 1000**5,
    "EB": 1000**6,
}
_BINARY_UNITS = {
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
    "PIB": 1024**5,
    "EIB": 1024**6,
}


@dataclass(frozen=True)
class BorgCreateProgress:
    original_bytes: int
    compressed_bytes: int
    deduplicated_bytes: int
    files: int
    path: str


def _size_bytes(value: bytes, unit: bytes) -> int:
    number = float(value.decode("ascii").replace(",", "."))
    normalized = unit.decode("ascii").upper()
    multiplier = _BINARY_UNITS.get(normalized, _DECIMAL_UNITS.get(normalized))
    if multiplier is None:
        raise ValueError(f"unsupported Borg progress unit: {normalized}")
    return max(0, int(number * multiplier))


def parse_borg_create_progress(record: bytes | str) -> BorgCreateProgress | None:
    payload = record.encode("utf-8", errors="replace") if isinstance(record, str) else bytes(record)
    match = _PROGRESS_RE.match(payload)
    if not match:
        return None
    try:
        return BorgCreateProgress(
            original_bytes=_size_bytes(match.group("original"), match.group("original_unit")),
            compressed_bytes=_size_bytes(match.group("compressed"), match.group("compressed_unit")),
            deduplicated_bytes=_size_bytes(match.group("deduplicated"), match.group("deduplicated_unit")),
            files=int(match.group("files")),
            path=(match.group("path") or b"").decode("utf-8", errors="replace").strip(),
        )
    except (TypeError, ValueError, OverflowError):
        return None


class BorgProgressStreamFilter:
    """Extract Borg create progress frames without polluting the run log.

    Borg 1.x has used two observable delimiters for the plain-text ``--progress``
    stream depending on version/output context: carriage returns for an in-place
    terminal display and normal newlines when stderr is a pipe.  Full ``--list``
    output can still contain millions of newline-delimited paths, so ordinary
    chunks keep a bytes-only fast path and are not split line-by-line unless they
    contain a plausible progress marker.

    A small carry buffer is used only for a plausible progress record at a chunk
    boundary.  Arbitrary file-list output is never accumulated.
    """

    _MAX_CARRY = 16 * 1024
    _PROGRESS_MARKERS = (b" O ", b" C ", b" D ", b" N")
    _PREFIX_RE = re.compile(
        rb"^\s*[0-9]+(?:[.,][0-9]+)?\s+(?:[kKMGTPE]?i?B)(?:\s+O(?:\s+.*)?)?$"
    )

    def __init__(self) -> None:
        self.latest: BorgCreateProgress | None = None
        self._carry = b""

    @classmethod
    def _candidate(cls, record: bytes) -> bool:
        return all(marker in record for marker in cls._PROGRESS_MARKERS)

    @classmethod
    def _could_be_progress_prefix(cls, record: bytes) -> bool:
        if not record or len(record) > cls._MAX_CARRY:
            return False
        # Once the O/C/D/N markers start appearing, keeping the tail until the
        # next delimiter is cheap and prevents losing a frame split by a pipe
        # read.  Before that, only accept a strict ``<number> <unit>`` prefix so
        # normal file paths are not buffered.
        if b" O " in record:
            return True
        return cls._PREFIX_RE.match(record) is not None

    def feed(self, data: bytes) -> tuple[bytes, BorgCreateProgress | None]:
        if not data:
            return data, None

        # Hot path for the normal high-volume --list stream.  Only inspect the
        # final unterminated fragment for the beginning of a progress frame; the
        # rest passes through byte-for-byte and retains object identity.
        if not self._carry and b"\r" not in data and b" O " not in data:
            last_lf = data.rfind(b"\n")
            tail = data[last_lf + 1:]
            if tail and self._could_be_progress_prefix(tail):
                self._carry = tail
                return data[:last_lf + 1], None
            return data, None

        payload = self._carry + data
        self._carry = b""
        output = bytearray()
        newest: BorgCreateProgress | None = None

        # splitlines(keepends=True) handles LF, CRLF and the CR-only progress
        # frames emitted by older Borg/TTY-style output.
        records = payload.splitlines(keepends=True)
        for index, framed in enumerate(records):
            terminated = framed.endswith((b"\n", b"\r"))
            if terminated:
                record = framed.rstrip(b"\r\n")
                if self._candidate(record):
                    progress = parse_borg_create_progress(record)
                    if progress is not None:
                        self.latest = newest = progress
                        continue
                output.extend(framed)
                continue

            # Only the final splitlines element can be unterminated.
            if index == len(records) - 1 and self._could_be_progress_prefix(framed):
                self._carry = framed
            else:
                output.extend(framed)

        return bytes(output), newest

    def finalize(self) -> tuple[bytes, BorgCreateProgress | None]:
        if not self._carry:
            return b"", None
        trailing = self._carry
        self._carry = b""
        progress = parse_borg_create_progress(trailing) if self._candidate(trailing) else None
        if progress is not None:
            self.latest = progress
            return b"", progress
        return trailing, None


_progress_lock = Lock()
_live_progress: dict[int, BorgCreateProgress] = {}
# Borg progress history is process-local and hard-bounded. It is retained only
# for current-source attribution and post-run per-source statistics; remaining
# time no longer depends on short-term rates or a growing trend history.
_live_progress_history: dict[int, deque[dict]] = {}


def set_run_progress(run_id: int, progress: BorgCreateProgress, *, timestamp: float | None = None) -> None:
    run_id = int(run_id)
    now = time.monotonic() if timestamp is None else float(timestamp)
    sample = {**asdict(progress), "timestamp": now}
    with _progress_lock:
        _live_progress[run_id] = progress
        history = _live_progress_history.setdefault(run_id, deque(maxlen=720))
        if history and (
            sample["original_bytes"] < history[-1]["original_bytes"]
            or sample["files"] < history[-1]["files"]
            or sample["deduplicated_bytes"] < history[-1]["deduplicated_bytes"]
        ):
            # Borg restarted/retried inside the same process: do not mix two
            # incompatible counter sequences in source-attribution history.
            history.clear()
        if history and now - float(history[-1]["timestamp"]) < 0.5:
            history[-1] = sample
        elif not history or any(
            sample[key] != history[-1][key]
            for key in ("original_bytes", "files", "deduplicated_bytes", "path")
        ):
            history.append(sample)


def get_run_progress(run_id: int) -> dict | None:
    with _progress_lock:
        progress = _live_progress.get(int(run_id))
        return asdict(progress) if progress is not None else None


def get_run_progress_history(run_id: int) -> list[dict]:
    with _progress_lock:
        return [dict(item) for item in _live_progress_history.get(int(run_id), ())]


def clear_run_progress(run_id: int) -> None:
    with _progress_lock:
        _live_progress.pop(int(run_id), None)
        _live_progress_history.pop(int(run_id), None)


_ITEM_ACTIVITY_RE = re.compile(
    rb"(?m)^[ \t]*(?:[Rr][Ee][Mm][Oo][Tt][Ee]:[ \t]*)?([AMCE])[ \t]+([^\r\n]+)\r?$"
)
_ADDED_MODIFIED_LINE_RE = re.compile(
    rb"(?m)^[ \t]*(?:[Rr][Ee][Mm][Oo][Tt][Ee]:[ \t]*)?[AM][ \t]+[^\r\n]*(?:\r?\n|$)"
)
_NETWORK_PREFIX = b"\x1eBBMNET\t"
_NETWORK_RECORD_RE = re.compile(
    rb"^\x1eBBMNET\t(?P<interface>[^\t\r\n]+)\t(?P<ip>[^\t\r\n]+)\t"
    rb"(?P<rx>[0-9]+)\t(?P<tx>[0-9]+)(?:\t(?P<route>[01]))?$"
)


@dataclass(frozen=True)
class BorgItemActivity:
    added: int = 0
    modified: int = 0
    changed: int = 0
    error: int = 0
    last_status: str = ""
    last_path: str = ""


class BorgItemActivityStreamFilter:
    """Count A/M/C/E item flags with a bounded, bytes-first parser.

    When the full file list is disabled Borg is invoked with ``--filter AMCE``.
    A/M lines are useful for the live counters but do not need to be persisted
    in the run log; C/E remain in the stream because the warning collector and
    the human-readable log need them. With the full file list enabled the input
    is returned byte-for-byte and only a C-regex scan is added.
    """

    def __init__(self, *, strip_added_modified: bool = False) -> None:
        self.strip_added_modified = bool(strip_added_modified)
        self._carry = b""
        self._counts = {"A": 0, "M": 0, "C": 0, "E": 0}
        self._last_status = ""
        self._last_path = ""

    def _consume_complete(self, complete: bytes) -> BorgItemActivity | None:
        if not complete:
            return None
        found = False
        last_status = b""
        last_path = b""
        for match in _ITEM_ACTIVITY_RE.finditer(complete):
            found = True
            raw_status = match.group(1)
            status = chr(raw_status[0])
            self._counts[status] += 1
            last_status = raw_status
            last_path = match.group(2)
        if not found:
            return None
        self._last_status = chr(last_status[0])
        # Only the newest path is needed by the UI. Avoid decoding every A/M
        # line during large first backups.
        self._last_path = last_path.decode("utf-8", errors="replace").strip()
        return BorgItemActivity(
            added=self._counts["A"],
            modified=self._counts["M"],
            changed=self._counts["C"],
            error=self._counts["E"],
            last_status=self._last_status,
            last_path=self._last_path,
        )

    def feed(self, data: bytes) -> tuple[bytes, BorgItemActivity | None]:
        if not data:
            return data, None
        payload = self._carry + data
        newline = payload.rfind(b"\n")
        if newline < 0:
            self._carry = payload
            # In pass-through mode the original bytes were already forwarded;
            # the carry exists only for status parsing across chunk boundaries.
            return (b"" if self.strip_added_modified else data), None
        complete = payload[: newline + 1]
        self._carry = payload[newline + 1 :]
        activity = self._consume_complete(complete)
        if not self.strip_added_modified:
            return data, activity
        return _ADDED_MODIFIED_LINE_RE.sub(b"", complete), activity

    def finalize(self) -> tuple[bytes, BorgItemActivity | None]:
        if not self._carry:
            return b"", None
        final = self._carry
        self._carry = b""
        activity = self._consume_complete(final)
        if self.strip_added_modified and _ADDED_MODIFIED_LINE_RE.fullmatch(final):
            return b"", activity
        return (final if self.strip_added_modified else b""), activity


@dataclass(frozen=True)
class NetworkInterfaceActivity:
    interface: str
    ip_address: str
    download_bits_per_second: float | None
    upload_bits_per_second: float | None
    route_selected: bool = False


@dataclass(frozen=True)
class NetworkActivity:
    interfaces: tuple[NetworkInterfaceActivity, ...]
    download_bytes: int = 0
    upload_bytes: int = 0
    route_interface: str = ""
    route_ip_address: str = ""


class BorgNetworkStreamFilter:
    """Strip client network telemetry and build a bounded live snapshot.

    The source client emits one tiny counter frame per monitored interface and
    second. Up to three interfaces are kept for the live UI, with the interface
    selected by the route to the repository ordered first. Cumulative job
    traffic is calculated from that route interface's kernel byte counters so
    it can be persisted when the run finishes. Ordinary Borg output retains the
    zero-copy fast path when no telemetry marker is present.
    """

    def __init__(self) -> None:
        self._carry = b""
        self._previous: dict[str, tuple[str, int, int, float]] = {}
        self._baseline_route: tuple[str, int, int] | None = None
        self._latest_interfaces: dict[str, NetworkInterfaceActivity] = {}
        self._route_interface = ""
        self._route_ip_address = ""
        self._download_bytes = 0
        self._upload_bytes = 0

    def _snapshot(self) -> NetworkActivity:
        interfaces = sorted(
            self._latest_interfaces.values(),
            key=lambda item: (not item.route_selected, item.interface),
        )[:3]
        return NetworkActivity(
            interfaces=tuple(interfaces),
            download_bytes=max(0, int(self._download_bytes)),
            upload_bytes=max(0, int(self._upload_bytes)),
            route_interface=self._route_interface,
            route_ip_address=self._route_ip_address,
        )

    def _parse(self, record: bytes) -> NetworkActivity | None:
        match = _NETWORK_RECORD_RE.match(record)
        if not match:
            return None
        try:
            interface = match.group("interface").decode("utf-8", errors="replace").strip()
            ip_address = match.group("ip").decode("utf-8", errors="replace").strip()
            rx = int(match.group("rx"))
            tx = int(match.group("tx"))
            route_selected = (match.group("route") or b"1") == b"1"
        except (TypeError, ValueError, OverflowError):
            return None
        now = time.monotonic()
        download = upload = None
        previous = self._previous.get(interface)
        if previous is not None:
            prev_ip, prev_rx, prev_tx, prev_time = previous
            delta = now - prev_time
            if ip_address == prev_ip and delta > 0 and rx >= prev_rx and tx >= prev_tx:
                download = ((rx - prev_rx) * 8.0) / delta
                upload = ((tx - prev_tx) * 8.0) / delta
        self._previous[interface] = (ip_address, rx, tx, now)

        if route_selected:
            if self._baseline_route is None or self._baseline_route[0] != interface:
                self._baseline_route = (interface, rx, tx)
                self._download_bytes = 0
                self._upload_bytes = 0
            else:
                _, base_rx, base_tx = self._baseline_route
                if rx >= base_rx:
                    self._download_bytes = rx - base_rx
                if tx >= base_tx:
                    self._upload_bytes = tx - base_tx
            self._route_interface = interface
            self._route_ip_address = ip_address

        self._latest_interfaces[interface] = NetworkInterfaceActivity(
            interface=interface,
            ip_address=ip_address,
            download_bits_per_second=download,
            upload_bits_per_second=upload,
            route_selected=route_selected,
        )
        # Keep memory bounded even on unusual hosts with many interfaces.
        ordered = sorted(
            self._latest_interfaces.values(),
            key=lambda item: (not item.route_selected, item.interface),
        )[:3]
        self._latest_interfaces = {item.interface: item for item in ordered}
        return self._snapshot()

    def feed(self, data: bytes) -> tuple[bytes, NetworkActivity | None]:
        if not data:
            return data, None
        if not self._carry and b"\x1e" not in data:
            return data, None
        payload = self._carry + data
        self._carry = b""
        output = bytearray()
        cursor = 0
        latest: NetworkActivity | None = None
        while True:
            marker = payload.find(_NETWORK_PREFIX, cursor)
            if marker < 0:
                suffix_start = payload.rfind(b"\x1e", cursor)
                if suffix_start >= 0 and _NETWORK_PREFIX.startswith(payload[suffix_start:]):
                    output.extend(payload[cursor:suffix_start])
                    self._carry = payload[suffix_start:]
                else:
                    output.extend(payload[cursor:])
                break
            output.extend(payload[cursor:marker])
            newline = payload.find(b"\n", marker)
            if newline < 0:
                self._carry = payload[marker:]
                break
            record = payload[marker:newline]
            parsed = self._parse(record)
            if parsed is None:
                output.extend(payload[marker:newline + 1])
            else:
                latest = parsed
            cursor = newline + 1
        return bytes(output), latest

    def finalize(self) -> tuple[bytes, NetworkActivity | None]:
        if not self._carry:
            return b"", self._snapshot() if self._latest_interfaces else None
        final = self._carry
        self._carry = b""
        parsed = self._parse(final.rstrip(b"\r\n"))
        return (b"" if parsed is not None else final), parsed or (self._snapshot() if self._latest_interfaces else None)


_live_activity_lock = Lock()
_live_item_activity: dict[int, BorgItemActivity] = {}
_live_network_activity: dict[int, tuple[NetworkActivity, float]] = {}


def set_run_item_activity(run_id: int, activity: BorgItemActivity, *, timestamp: float | None = None) -> None:
    # Only the latest cumulative A/M/C/E counters are needed by the live UI.
    # The previous ETA-specific item history was removed to avoid retaining
    # state that no longer contributes to progress or remaining-time math.
    del timestamp
    with _live_activity_lock:
        _live_item_activity[int(run_id)] = activity


def get_run_item_activity(run_id: int) -> dict | None:
    with _live_activity_lock:
        activity = _live_item_activity.get(int(run_id))
        return asdict(activity) if activity is not None else None


def set_run_network_activity(run_id: int, activity: NetworkActivity) -> None:
    with _live_activity_lock:
        _live_network_activity[int(run_id)] = (activity, time.monotonic())


def get_run_network_activity(run_id: int, *, max_age_seconds: float | None = 5.0) -> dict | None:
    with _live_activity_lock:
        stored = _live_network_activity.get(int(run_id))
        if stored is None:
            return None
        activity, sampled_at = stored
        if max_age_seconds is not None and time.monotonic() - sampled_at > max(1.0, float(max_age_seconds)):
            _live_network_activity.pop(int(run_id), None)
            return None
        return asdict(activity)


def clear_run_live_activity(run_id: int) -> None:
    with _live_activity_lock:
        _live_item_activity.pop(int(run_id), None)
        _live_network_activity.pop(int(run_id), None)
