"""Unit tests for common/time_utils.py."""
from datetime import datetime, timezone, timedelta

from common.time_utils import normalize_datetime, parse_iso_timestamp


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


# ---- parse_iso_timestamp ----

def test_parse_iso_timestamp_parses_a_real_archived_timestamp() -> None:
    assert parse_iso_timestamp("2026-07-25T16:31:47.399383") == datetime(2026, 7, 25, 16, 31, 47, 399383)


def test_parse_iso_timestamp_none_for_empty_string() -> None:
    assert parse_iso_timestamp("") is None


def test_parse_iso_timestamp_none_for_missing_value() -> None:
    assert parse_iso_timestamp(None) is None


def test_parse_iso_timestamp_none_for_malformed_value() -> None:
    assert parse_iso_timestamp("not-a-timestamp") is None
