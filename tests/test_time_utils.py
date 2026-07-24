"""Unit tests for utils/time_utils.py."""
from datetime import datetime, timezone, timedelta

from utils.time_utils import normalize_datetime


def test_normalize_datetime_none_returns_none() -> None:
    assert normalize_datetime(None) is None


def test_normalize_datetime_naive_returned_as_is() -> None:
    naive = datetime(2025, 11, 30, 16, 51, 22)
    assert normalize_datetime(naive) == naive
    assert normalize_datetime(naive).tzinfo is None


def test_normalize_datetime_utc_aware_strips_tzinfo() -> None:
    aware = datetime(2025, 11, 30, 16, 51, 22, tzinfo=timezone.utc)
    result = normalize_datetime(aware)
    assert result == datetime(2025, 11, 30, 16, 51, 22)
    assert result.tzinfo is None


def test_normalize_datetime_non_utc_aware_converts_to_utc_first() -> None:
    plus_three = timezone(timedelta(hours=3))
    aware = datetime(2025, 11, 30, 19, 0, 0, tzinfo=plus_three)
    result = normalize_datetime(aware)
    assert result == datetime(2025, 11, 30, 16, 0, 0)
    assert result.tzinfo is None
