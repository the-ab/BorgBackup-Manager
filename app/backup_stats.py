from __future__ import annotations

import json
import re
from typing import Any

_ARCHIVE_NAME_RE = re.compile(r"^Archive name:\s*(?P<name>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_FILE_COUNT_RE = re.compile(r"^Number of files:\s*(?P<count>\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_THIS_ARCHIVE_RE = re.compile(
    r"^This archive:\s*(?P<original>.+?)\s{2,}(?P<compressed>.+?)\s{2,}(?P<deduplicated>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SIZE_RE = re.compile(
    r"^\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>B|bytes?|kB|MB|GB|TB|PB|EB|KiB|MiB|GiB|TiB|PiB|EiB)\s*$",
    re.IGNORECASE,
)

_DECIMAL_UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "pb": 1000**5,
    "eb": 1000**6,
}
_BINARY_UNITS = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
    "eib": 1024**6,
}



_SOURCE_SCAN_MARKER_RE = re.compile(r"^BBM_SOURCE_STATS_JSON=(?P<payload>\{.*\})\s*$", re.MULTILINE)


def parse_source_scan_statistics(text: str | None) -> dict[str, Any]:
    """Extract a BBM live source-scan result from mixed remote output."""
    if not text:
        return {}
    matches = list(_SOURCE_SCAN_MARKER_RE.finditer(text))
    if not matches:
        return {}
    try:
        payload = json.loads(matches[-1].group("payload"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        size = max(0, int(payload.get("size_bytes")))
        count = max(0, int(payload.get("file_count")))
    except (TypeError, ValueError):
        return {}
    return {
        "original_size_bytes": size,
        "file_count": count,
        "scan_method": str(payload.get("method") or "live-scan"),
        "warning_count": max(0, int(payload.get("warning_count") or 0)),
    }

def parse_human_size(value: str) -> int | None:
    """Convert Borg's human-readable size value to bytes."""
    match = _SIZE_RE.fullmatch(value.strip())
    if not match:
        return None
    number = float(match.group("number").replace(",", "."))
    unit = match.group("unit").casefold()
    multiplier = _DECIMAL_UNITS.get(unit, _BINARY_UNITS.get(unit))
    if multiplier is None:
        return None
    return max(0, int(round(number * multiplier)))


def parse_backup_statistics(text: str | None) -> dict[str, Any]:
    """Extract the final ``This archive`` statistics from ``borg create`` output."""
    if not text:
        return {}
    archive_matches = list(_ARCHIVE_NAME_RE.finditer(text))
    statistics_matches = list(_THIS_ARCHIVE_RE.finditer(text))
    if not statistics_matches:
        return {}
    match = statistics_matches[-1]
    result: dict[str, Any] = {
        "original_size_bytes": parse_human_size(match.group("original")),
        "compressed_size_bytes": parse_human_size(match.group("compressed")),
        "deduplicated_size_bytes": parse_human_size(match.group("deduplicated")),
    }
    file_matches = list(_FILE_COUNT_RE.finditer(text))
    if file_matches:
        result["file_count"] = max(0, int(file_matches[-1].group("count")))
    if archive_matches:
        result["archive_name"] = archive_matches[-1].group("name").strip()
    return result
