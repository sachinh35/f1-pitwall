"""Unit tests for utils/live_persistence.py."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import F1Session
from utils import live_persistence
from utils.live_persistence import _parse_rc_timestamp, _to_float, _to_int, _to_naive_utc
from utils.session_state import CompletedLap, LapAggregates, QualifyingResultEntry, TelemetrySampleBuffer

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
    event_time = datetime(2026, 7, 25, 16, 31, 47)

    await live_persistence.persist_weather_snapshot(
        9850,
        {"AirTemp": "25.1", "TrackTemp": "30.8", "Humidity": "50.0", "Rainfall": "0", "WindSpeed": "1.4", "WindDirection": "350"},
        ts=event_time,
    )

    mock_conn.execute.assert_awaited_once()
    query, *args = mock_conn.execute.call_args.args
    assert "ON CONFLICT (session_key, ts) DO NOTHING" in query
    assert args[0] == 9850  # session_key
    assert args[1] == event_time  # ts - the real event time, not insertion time
    assert args[2] == 25.1  # air_temp


@pytest.mark.asyncio
async def test_persist_weather_snapshot_normalizes_a_tz_aware_ts(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    aware_ts = datetime(2026, 7, 25, 16, 31, 47, tzinfo=timezone.utc)

    await live_persistence.persist_weather_snapshot(9850, {"AirTemp": "25.1"}, ts=aware_ts)

    ts_arg = mock_conn.execute.call_args.args[2]
    assert ts_arg == datetime(2026, 7, 25, 16, 31, 47)
    assert ts_arg.tzinfo is None


@pytest.mark.asyncio
async def test_persist_weather_snapshot_falls_back_to_now_when_ts_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_weather_snapshot(9850, {"AirTemp": "25.1"}, ts=None)

    ts_arg = mock_conn.execute.call_args.args[2]
    assert ts_arg.tzinfo is None
    assert (datetime.now(timezone.utc).replace(tzinfo=None) - ts_arg).total_seconds() < 5


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
    # query, meeting_key, session_key, date, category, message, scope, sector, driver_number, flag, message_index
    assert args[6] == "Driver"  # scope
    assert args[8] == 44  # driver_number


@pytest.mark.asyncio
async def test_persist_race_control_entry_includes_message_index_for_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_race_control_entry(
        9850, 1275, {"Utc": "2025-11-30T15:57:04", "Message": "Green flag", "index": "4"}
    )

    args = mock_conn.execute.call_args.args
    # query, meeting_key, session_key, date, category, message, scope, sector, driver_number, flag, message_index
    assert "ON CONFLICT (session_key, message_index) DO NOTHING" in args[0]
    assert args[10] == 4  # message_index, parsed from entry["index"]


@pytest.mark.asyncio
async def test_persist_race_control_entry_message_index_is_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Historical OpenF1-sourced entries (Garage Mode's batch path) have no index at all -
    must store NULL, not crash or coerce to some fake value."""
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_race_control_entry(9850, 1275, {"Utc": "2025-11-30T15:57:04", "Message": "test"})

    args = mock_conn.execute.call_args.args
    assert args[10] is None


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


# ---- persist_completed_lap (mocked DB) ----

def _sample_completed_lap(gap_to_ahead_seconds=1.1) -> CompletedLap:
    buffer = TelemetrySampleBuffer()
    buffer.add_car_sample(
        utc=datetime(2025, 11, 30, 16, 0, 0), rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12
    )
    return CompletedLap(
        driver_number=44,
        lap_number=12,
        lap_duration_seconds=87.150,
        aggregates=LapAggregates(avg_speed_kmh=300, max_speed_kmh=300, avg_throttle_pct=100, drs_active_pct=100),
        telemetry=buffer,
        gap_to_ahead_seconds=gap_to_ahead_seconds,
    )


@pytest.mark.asyncio
async def test_persist_completed_lap_includes_gap_to_ahead_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_completed_lap(9850, 1275, _sample_completed_lap(gap_to_ahead_seconds=1.05))

    lap_data_call_args = mock_conn.execute.call_args_list[0].args
    # query, meeting_key, session_key, driver_number, lap_number, lap_duration, avg_speed_kmh,
    # max_speed_kmh, avg_throttle_pct, drs_active_pct, gap_to_ahead_seconds, qualifying_part
    assert lap_data_call_args[-2] == pytest.approx(1.05)


@pytest.mark.asyncio
async def test_persist_completed_lap_gap_to_ahead_seconds_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_completed_lap(9850, 1275, _sample_completed_lap(gap_to_ahead_seconds=None))

    lap_data_call_args = mock_conn.execute.call_args_list[0].args
    assert lap_data_call_args[-2] is None


@pytest.mark.asyncio
async def test_persist_completed_lap_includes_qualifying_part(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    lap = _sample_completed_lap()
    lap.qualifying_part = "Q2"

    await live_persistence.persist_completed_lap(9850, 1275, lap)

    lap_data_call_args = mock_conn.execute.call_args_list[0].args
    assert lap_data_call_args[-1] == "Q2"


# ---- mark_lap_deleted (mocked DB) ----

@pytest.mark.asyncio
async def test_mark_lap_deleted_updates_matching_row(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    mock_conn.execute.return_value = "UPDATE 1"

    await live_persistence.mark_lap_deleted(9850, 55, 3)

    mock_conn.execute.assert_awaited_once_with(
        """
            UPDATE lap_data SET is_deleted = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE session_key = $1 AND driver_number = $2 AND lap_number = $3
            """,
        9850, 55, 3,
    )


@pytest.mark.asyncio
async def test_mark_lap_deleted_logs_a_warning_when_no_row_matched(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mock_conn = _mock_db(monkeypatch)
    mock_conn.execute.return_value = "UPDATE 0"

    with caplog.at_level("WARNING"):
        await live_persistence.mark_lap_deleted(9850, 55, 3)

    assert any("no lap_data row" in record.message for record in caplog.records)


# ---- persist_qualifying_results (mocked DB) ----

@pytest.mark.asyncio
async def test_persist_qualifying_results_upserts_every_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    results = [
        QualifyingResultEntry(
            driver_number=1, qualifying_part="Q1", position=1,
            best_lap_seconds=80.0, gap_to_leader_seconds=0.0, eliminated=False,
        ),
        QualifyingResultEntry(
            driver_number=22, qualifying_part="Q1", position=22,
            best_lap_seconds=None, gap_to_leader_seconds=None, eliminated=True,
        ),
    ]

    await live_persistence.persist_qualifying_results(9850, 1275, results)

    mock_conn.executemany.assert_awaited_once()
    query, rows = mock_conn.executemany.call_args.args
    assert "ON CONFLICT (session_key, qualifying_part, driver_number)" in query
    assert rows == [
        (9850, 1275, 1, "Q1", 1, 80.0, 0.0, False),
        (9850, 1275, 22, "Q1", 22, None, None, True),
    ]


@pytest.mark.asyncio
async def test_persist_qualifying_results_no_op_for_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_qualifying_results(9850, 1275, [])

    mock_conn.executemany.assert_not_awaited()


# ---- persist_total_laps (mocked DB) ----

@pytest.mark.asyncio
async def test_persist_total_laps_executes_update(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)

    await live_persistence.persist_total_laps(9850, 57)

    mock_conn.execute.assert_awaited_once_with(
        "UPDATE sessions SET total_laps = $2 WHERE session_key = $1", 9850, 57
    )
