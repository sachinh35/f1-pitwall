"""Unit tests for utils/live_persistence.py."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import F1Session
from utils import live_persistence
from utils.live_persistence import _parse_rc_timestamp, _to_float, _to_int, _to_naive_utc

# date_start/date_end are timezone-aware here on purpose - that's exactly what OpenF1 actually
# returns, and what previously blew up asyncpg's plain-TIMESTAMP codec (see _to_naive_utc).
_SAMPLE_SESSION_META = F1Session(
    circuit_key=63,
    circuit_short_name="Losail",
    country_code="QAT",
    country_key=10,
    country_name="Qatar",
    date_end=datetime(2025, 11, 30, 18, 0, 0, tzinfo=timezone.utc),
    date_start=datetime(2025, 11, 30, 16, 0, 0, tzinfo=timezone.utc),
    gmt_offset="03:00:00",
    location="Lusail",
    meeting_key=1275,
    session_key=9850,
    session_name="Race",
    session_type="Race",
    year=2025,
)

_SAMPLE_DRIVER = DriverInfo(
    meeting_key=1275,
    session_key=9850,
    driver_number=1,
    broadcast_name="M VERSTAPPEN",
    full_name="Max Verstappen",
    name_acronym="VER",
    team_name="Red Bull Racing",
    team_colour="3671C6",
    first_name="Max",
    last_name="Verstappen",
    headshot_url="https://example.com/ver.png",
    country_code="NED",
)


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
    """Patch DatabaseManager.get_connection to a mock async-context-manager, returning the mock connection.
    conn.transaction() is also wired up as a (no-op) async context manager, for functions that wrap
    multiple statements in one transaction (e.g. persist_driver_roster)."""
    mock_conn = AsyncMock()

    class _FakeTransactionCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    mock_conn.transaction = MagicMock(return_value=_FakeTransactionCtx())

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


# ---- _to_naive_utc ----

def test_to_naive_utc_strips_tzinfo_after_converting_to_utc() -> None:
    aware = datetime(2025, 11, 30, 18, 0, 0, tzinfo=timezone.utc)
    result = _to_naive_utc(aware)
    assert result == datetime(2025, 11, 30, 18, 0, 0)
    assert result.tzinfo is None


def test_to_naive_utc_leaves_naive_datetime_untouched() -> None:
    naive = datetime(2025, 11, 30, 18, 0, 0)
    assert _to_naive_utc(naive) == naive


# ---- persist_session_metadata / persist_driver_roster (mocked DB) ----

@pytest.mark.asyncio
async def test_persist_session_metadata_executes_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_session_metadata(_SAMPLE_SESSION_META)

    mock_conn.execute.assert_awaited_once()
    args = mock_conn.execute.call_args.args
    # query, session_key, meeting_key, session_name, session_type, ...
    assert args[1] == 9850  # session_key
    assert args[2] == 1275  # meeting_key
    assert args[9] == "Lusail"  # location
    assert args[10] == datetime(2025, 11, 30, 16, 0, 0)  # date_start, tz stripped
    assert args[10].tzinfo is None


@pytest.mark.asyncio
async def test_persist_driver_roster_executes_one_upsert_per_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    second_driver = _SAMPLE_DRIVER.model_copy(update={"driver_number": 44, "name_acronym": "HAM"})

    await live_persistence.persist_driver_roster(9850, [_SAMPLE_DRIVER, second_driver])

    assert mock_conn.execute.await_count == 2
    first_call_args = mock_conn.execute.call_args_list[0].args
    # query, session_key, driver_number, broadcast_name, full_name, name_acronym, ...
    assert first_call_args[1] == 9850  # session_key
    assert first_call_args[2] == 1  # driver_number
    assert first_call_args[5] == "VER"  # name_acronym


@pytest.mark.asyncio
async def test_persist_driver_roster_no_op_for_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_driver_roster(9850, [])

    mock_conn.execute.assert_not_awaited()


# ---- persist_confirmed_driver_roster (mocked DB) ----

@pytest.mark.asyncio
async def test_persist_confirmed_driver_roster_executes_one_upsert_per_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    entries = [
        ConfirmedRosterEntry(driver_number=1, tla="NOR", full_name="Lando Norris", team_name="McLaren"),
        ConfirmedRosterEntry(driver_number=81, tla="OWA", full_name="Pato O'Ward", team_name="McLaren"),
    ]

    await live_persistence.persist_confirmed_driver_roster(9850, entries)

    assert mock_conn.execute.await_count == 2
    first_call_args = mock_conn.execute.call_args_list[0].args
    # query, session_key, driver_number, full_name, name_acronym, team_name
    assert first_call_args[1] == 9850  # session_key
    assert first_call_args[2] == 1  # driver_number
    assert first_call_args[3] == "Lando Norris"  # full_name
    assert first_call_args[4] == "NOR"  # name_acronym (tla)
    assert first_call_args[5] == "McLaren"  # team_name


@pytest.mark.asyncio
async def test_persist_confirmed_driver_roster_no_op_for_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_confirmed_driver_roster(9850, [])

    mock_conn.execute.assert_not_awaited()
