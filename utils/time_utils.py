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
