from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APP_TIMEZONE_NAME = os.getenv("TZ", "Europe/Berlin") or "Europe/Berlin"
try:
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    APP_TIMEZONE_NAME = "Europe/Berlin"
    APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime.

    SQLite drops timezone information even for DateTime(timezone=True). Values
    read back without an offset are therefore interpreted as UTC, because all
    application timestamps are stored in UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    aware = ensure_utc(value)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


def normalize_borg_timestamp(value: object) -> str | None:
    """Return a timezone-aware ISO timestamp for Borg archive metadata.

    Borg 1.x commonly emits archive timestamps without an offset. Those values
    are local times from the Borg client, not UTC. The manager operates in the
    configured application timezone (Europe/Berlin by default), so attach that
    timezone to naive Borg values while preserving explicit offsets unchanged.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value.strip()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed.isoformat()
