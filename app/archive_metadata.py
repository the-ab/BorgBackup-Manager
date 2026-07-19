from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from app.time_utils import APP_TIMEZONE


_CHECKPOINT_SUFFIX_RE = re.compile(r"\.checkpoint(?:\.\d+)?$", re.IGNORECASE)
_ISO_TIMESTAMP_RE = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)$"
)
_FILENAME_TIMESTAMP_RE = re.compile(
    r"(?P<stamp>\d{4}-\d{2}-\d{2}[T_ -]\d{2}[-:]\d{2}(?:[-:]\d{2}(?:\.\d+)?)?)$"
)
_MANAGER_PREFIXES = (
    re.compile(r"^bbm-job-\d+-[0-9a-f]{8,64}-", re.IGNORECASE),
    re.compile(r"^bbm-job-\d+-", re.IGNORECASE),
    re.compile(r"^bbm-\d+-", re.IGNORECASE),
)


def _without_checkpoint_suffix(name: str) -> str:
    return _CHECKPOINT_SUFFIX_RE.sub("", name.strip())


def _timestamp_match(name: str) -> re.Match[str] | None:
    base = _without_checkpoint_suffix(name)
    return _ISO_TIMESTAMP_RE.search(base) or _FILENAME_TIMESTAMP_RE.search(base)


def archive_timestamp_from_name(name: str) -> datetime | None:
    """Extract a timestamp from common Borg archive naming templates."""
    base = _without_checkpoint_suffix(name)
    match = _timestamp_match(base)
    if not match:
        return None
    value = match.group("stamp")
    if "T" not in value:
        # Accept ``YYYY-MM-DD_HH-MM-SS`` and similar filename-safe variants.
        value = value[:10] + "T" + value[11:]
    date_part, time_part = value.split("T", 1)
    timezone_suffix = ""
    timezone_match = re.search(r"(Z|[+-]\d{2}:?\d{2})$", time_part)
    if timezone_match:
        timezone_suffix = timezone_match.group(1)
        time_part = time_part[: -len(timezone_suffix)]
    time_part = re.sub(r"-", ":", time_part)
    value = f"{date_part}T{time_part}{timezone_suffix}".replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed


def infer_archive_device(name: str) -> str | None:
    """Infer a device identifier solely from an archive name.

    The inference intentionally does not depend on a configured Host or Job.
    It recognises current and historical BorgBackup Manager prefixes as well as
    common ``<device>-<timestamp>`` archive templates, with or without seconds.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    base = _without_checkpoint_suffix(name)
    match = _timestamp_match(base)
    if not match:
        return None
    candidate = base[: match.start()].rstrip("-_. ")
    for pattern in _MANAGER_PREFIXES:
        candidate = pattern.sub("", candidate, count=1)
    candidate = candidate.strip("-_. ")
    return candidate or None


def _parse_archive_start(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed


def archive_sort_key(archive: dict[str, Any]) -> tuple[int, float, str]:
    timestamp = _parse_archive_start(archive.get("start"))
    if timestamp is None:
        timestamp = archive_timestamp_from_name(str(archive.get("name") or ""))
    return (
        1 if timestamp is not None else 0,
        timestamp.timestamp() if timestamp is not None else float("-inf"),
        str(archive.get("name") or "").casefold(),
    )


def sort_archives_newest_first(archives: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return archives in deterministic newest-to-oldest order."""
    return sorted(archives, key=archive_sort_key, reverse=True)


def annotate_archive_devices(archives: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(archives)
    for archive in result:
        archive["archive_device"] = infer_archive_device(str(archive.get("name") or ""))
    return result
