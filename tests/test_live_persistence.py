"""Unit tests for utils/live_persistence.py."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import live_persistence
from utils.live_persistence import _parse_rc_timestamp, _to_float, _to_int


# ---- pure coercion helpers ----

@pytest.mark.parametrize("value,expected", [("25.1", 25.1), (None, None), ("", None), ("not-a-number", None)])
def test_to_float(value, expected) -> None:
    assert _to_float(value) == expected


@pytest.mark.parametrize("value,expected", [("3", 3), ("3.0", 3), (None, None), ("bad", None)])
def test_to_int(value, expected) -> None:
    assert _to_int(value) == expected


def test_parse_rc_timestamp_handles_no_fractional_seconds_no_z_suffix() -> None:
    assert _parse_rc_timestamp("2025-11-30T15:57:04") == datetime(2025, 11, 30, 15, 57, 4)


def test_parse_rc_timestamp_returns_none_for_garbage() -> None:
    assert _parse_rc_timestamp("not-a-timestamp") is None
    assert _parse_rc_timestamp(None) is None


# ---- persist_weather_snapshot / persist_race_control_entry (mocked DB) ----

def _mock_db(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Patch DatabaseManager.get_connection to a mock async-context-manager, returning the mock connection."""
    mock_conn = AsyncMock()

    class _FakeConnCtx:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(live_persistence.DatabaseManager, "get_connection", MagicMock(return_value=_FakeConnCtx()))
    return mock_conn


@pytest.mark.asyncio
async def test_persist_weather_snapshot_executes_insert_with_coerced_values(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_weather_snapshot(
        9850, {"AirTemp": "25.1", "TrackTemp": "30.8", "Humidity": "50.0", "Rainfall": "0", "WindSpeed": "1.4", "WindDirection": "350"}
    )

    mock_conn.execute.assert_awaited_once()
    args = mock_conn.execute.call_args.args
    assert args[1] == 9850  # session_key
    assert args[2] == 25.1  # air_temp


@pytest.mark.asyncio
async def test_persist_race_control_entry_skips_when_meeting_key_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_race_control_entry(9850, None, {"Utc": "2025-11-30T15:57:04", "Message": "test"})

    mock_conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_race_control_entry_skips_when_timestamp_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_race_control_entry(9850, 1275, {"Utc": "garbage", "Message": "test"})

    mock_conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_race_control_entry_infers_driver_scope_when_racing_number_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_race_control_entry(
        9850, 1275, {"Utc": "2025-11-30T15:57:04", "Message": "Track limits", "RacingNumber": "44"}
    )

    mock_conn.execute.assert_awaited_once()
    args = mock_conn.execute.call_args.args
    # query, meeting_key, session_key, date, category, message, scope, sector, driver_number, flag
    assert args[6] == "Driver"  # scope
    assert args[8] == 44  # driver_number
