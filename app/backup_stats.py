from __future__ import annotations

import re
from typing import Any

_ARCHIVE_NAME_RE = re.compile(r"^Archive name:\s*(?P<name>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
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
    if archive_matches:
        result["archive_name"] = archive_matches[-1].group("name").strip()
    return result
