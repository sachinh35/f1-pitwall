"""Shared datetime normalization helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize a datetime to naive (timezone-unaware) UTC for PostgreSQL TIMESTAMP storage.

    If timezone-aware, converts to UTC and strips tzinfo. If already naive, returned as-is.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO 8601 timestamp string (as written by RawStreamArchiver/LiveSessionPipeline's
    raw-archive "timestamp" field - naive, local system time from `datetime.now().isoformat()`)
    back into a datetime. Returns None for missing/malformed input rather than raising, since a
    single bad line in a captured log must never take down a replay/tail.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
