from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.archive_metadata import sort_archives_newest_first
from app.time_utils import APP_TIMEZONE, normalize_borg_timestamp


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _path(payload: Any, *keys: str) -> Any:
    value = payload
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _parse_datetime(value: Any) -> datetime | None:
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


def _duration_seconds(item: dict[str, Any]) -> float | None:
    explicit = item.get("duration")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool) and explicit >= 0:
        return float(explicit)
    start = _parse_datetime(item.get("start") or item.get("time"))
    end = _parse_datetime(item.get("end"))
    if start and end:
        try:
            return max(0.0, (end - start).total_seconds())
        except TypeError:
            return None
    return None


def _archive_stats(item: dict[str, Any]) -> dict[str, Any]:
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    return {
        "name": str(item.get("name") or item.get("archive") or ""),
        "id": item.get("id"),
        "start": normalize_borg_timestamp(item.get("start") or item.get("time")),
        "end": normalize_borg_timestamp(item.get("end")),
        "duration": _duration_seconds(item),
        "hostname": item.get("hostname"),
        "username": item.get("username"),
        "comment": item.get("comment") or "",
        "command_line": item.get("command_line") if isinstance(item.get("command_line"), list) else [],
        "nfiles": _number(stats.get("nfiles")),
        "original_size": _number(stats.get("original_size")),
        "compressed_size": _number(stats.get("compressed_size")),
        "deduplicated_size": _number(stats.get("deduplicated_size")),
        "max_archive_size_utilization": (
            item.get("limits", {}).get("max_archive_size")
            if isinstance(item.get("limits"), dict)
            and isinstance(item.get("limits", {}).get("max_archive_size"), (int, float))
            else None
        ),
    }


def load_borg_json_document(output: str, *, expected_keys: set[str] | None = None) -> Any:
    """Decode one Borg JSON document even when harmless wrapper text surrounds it.

    Borg normally writes JSON exclusively to stdout. Some Borg/OpenSSH/runuser
    combinations can nevertheless prepend or append informational text while
    still returning rc 0 or 1. The decoder first requires normal JSON and only
    then scans for a complete object with the expected Borg top-level keys. It
    never evaluates text and ignores nested unrelated JSON fragments.
    """
    text = str(output or "").lstrip("\ufeff")
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_error:
        decoder = json.JSONDecoder()
        expected = set(expected_keys or ())
        for index, character in enumerate(text):
            if character not in "{[":
                continue
            try:
                payload, _end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            if expected:
                if not isinstance(payload, dict) or not expected.intersection(payload):
                    continue
            return payload
        raise original_error


def parse_borg_info(output: str) -> dict[str, Any]:
    """Normalize Borg 1.2–1.4 ``info --json`` output.

    Borg exposes repository totals in cache/repository statistics and detailed
    archive statistics in an ``archives`` list.  Some commands return a single
    ``archive`` object, so both shapes are accepted.
    """
    try:
        payload: Any = load_borg_json_document(
            output,
            expected_keys={"archives", "archive", "cache", "repository", "encryption", "stats"},
        )
    except json.JSONDecodeError as exc:
        raise ValueError("Borg-Informationsausgabe ist kein gültiges JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Borg-Informationsausgabe besitzt eine unerwartete Struktur")

    stats_candidates = [
        _path(payload, "cache", "stats"),
        _path(payload, "repository", "stats"),
        payload.get("stats"),
    ]
    repository_stats: dict[str, Any] = {}
    for candidate in stats_candidates:
        if not isinstance(candidate, dict):
            continue
        original = _number(candidate.get("total_size"))
        compressed = _number(candidate.get("total_csize"))
        deduplicated = _number(candidate.get("unique_csize"))
        unique_uncompressed = _number(candidate.get("unique_size"))
        if any(value is not None for value in (original, compressed, deduplicated, unique_uncompressed)):
            repository_stats = {
                "original_size": original,
                "compressed_size": compressed,
                "deduplicated_size": deduplicated,
                "deduplicated_uncompressed_size": unique_uncompressed,
                "total_chunks": _number(candidate.get("total_chunks")),
                "unique_chunks": _number(candidate.get("total_unique_chunks")),
            }
            break

    raw_archives: list[Any] = []
    if isinstance(payload.get("archives"), list):
        raw_archives.extend(payload["archives"])
    if isinstance(payload.get("archive"), dict):
        raw_archives.append(payload["archive"])
    archives = [_archive_stats(item) for item in raw_archives if isinstance(item, dict)]
    archives = sort_archives_newest_first(item for item in archives if item["name"])

    return {
        "repository": repository_stats,
        "archives": archives,
        "encryption": payload.get("encryption") if isinstance(payload.get("encryption"), dict) else {},
        "repository_metadata": payload.get("repository") if isinstance(payload.get("repository"), dict) else {},
    }


def merge_archive_statistics(archives: list[dict[str, Any]], details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {str(item.get("name")): item for item in details if item.get("name")}
    for archive in archives:
        detail = by_name.get(str(archive.get("name")))
        if not detail:
            continue
        for key in (
            "end", "duration", "hostname", "username", "comment", "nfiles",
            "original_size", "compressed_size", "deduplicated_size",
            "max_archive_size_utilization",
        ):
            if detail.get(key) is not None:
                archive[key] = detail[key]
    return sort_archives_newest_first(archives)
