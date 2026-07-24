"""
Equivalence tests for the DRY-refactored utils/lap_data.py (Milestone 2) -
verifies get_lap_data_for_session still wires check/get/fetch/insert together
correctly after moving that orchestration into the shared get_or_fetch()
helper, which is itself covered in isolation by test_cache_first_fetch.py.
stints.py/race_control.py share the identical pattern and aren't repeated
here in full - each gets its own lighter smoke test below.
"""
from unittest.mock import AsyncMock

import pytest

from api_pydantic_models.lap_data import LapDataDB
from utils import lap_data, race_control, stints


@pytest.mark.asyncio
async def test_get_lap_data_for_session_cache_hit_skips_openf1(monkeypatch: pytest.MonkeyPatch) -> None:
    db_row = LapDataDB(
        meeting_key=1275, session_key=9850, driver_number=1, lap_number=1,
        date_start=None, duration_sector_1=None, duration_sector_2=None, duration_sector_3=None,
        lap_duration=87.15, i1_speed=None, i2_speed=None, st_speed=None, is_pit_out_lap=False,
        segments_sector_1=None, segments_sector_2=None, segments_sector_3=None,
    )
    check_exists = AsyncMock(return_value=True)
    get_from_db = AsyncMock(return_value=[db_row])
    fetch_from_openf1 = AsyncMock()

    monkeypatch.setattr(lap_data, "check_session_data_exists", check_exists)
    monkeypatch.setattr(lap_data, "get_lap_data_from_db", get_from_db)
    monkeypatch.setattr(lap_data, "fetch_laps_from_openf1", fetch_from_openf1)

    result = await lap_data.get_lap_data_for_session(session_key=9850, driver_numbers=[1])

    assert len(result) == 1
    assert result[0].lap_duration == 87.15
    fetch_from_openf1.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_lap_data_for_session_filters_to_requested_drivers(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        LapDataDB(meeting_key=1, session_key=9850, driver_number=1, lap_number=1, date_start=None,
                  duration_sector_1=None, duration_sector_2=None, duration_sector_3=None, lap_duration=None,
                  i1_speed=None, i2_speed=None, st_speed=None, is_pit_out_lap=False,
                  segments_sector_1=None, segments_sector_2=None, segments_sector_3=None),
        LapDataDB(meeting_key=1, session_key=9850, driver_number=4, lap_number=1, date_start=None,
                  duration_sector_1=None, duration_sector_2=None, duration_sector_3=None, lap_duration=None,
                  i1_speed=None, i2_speed=None, st_speed=None, is_pit_out_lap=False,
                  segments_sector_1=None, segments_sector_2=None, segments_sector_3=None),
    ]
    monkeypatch.setattr(lap_data, "check_session_data_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(lap_data, "get_lap_data_from_db", AsyncMock(return_value=rows))

    # Requested only driver 1, even though the DB query (which itself filters
    # server-side) hypothetically returned both - the response model must not
    # leak driver 4's data back to a caller that only asked for driver 1.
    result = await lap_data.get_lap_data_for_session(session_key=9850, driver_numbers=[1])
    assert [r.driver_number for r in result] == [1]


@pytest.mark.asyncio
async def test_get_stints_for_session_cache_miss_fetches_converts_and_inserts(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_pydantic_models.stints import StintDB
    from openf1_pydantic_models.f1_stints import F1Stint

    openf1_stint = F1Stint(
        meeting_key=1275, session_key=9850, driver_number=1, stint_number=1,
        lap_start=1, lap_end=20, compound="MEDIUM", tyre_age_at_start=0,
    )
    db_row = StintDB(meeting_key=1275, session_key=9850, driver_number=1, stint_number=1,
                      lap_start=1, lap_end=20, compound="MEDIUM", tyre_age_at_start=0)

    monkeypatch.setattr(stints, "check_session_stints_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(stints, "fetch_stints_from_openf1", AsyncMock(return_value=[openf1_stint]))
    insert_batch = AsyncMock()
    monkeypatch.setattr(stints, "insert_stints_batch", insert_batch)
    monkeypatch.setattr(stints, "get_stints_from_db", AsyncMock(return_value=[db_row]))

    result = await stints.get_stints_for_session(9850)

    insert_batch.assert_awaited_once()
    assert len(result) == 1
    assert result[0].compound == "MEDIUM"


@pytest.mark.asyncio
async def test_get_race_control_events_for_session_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    from api_pydantic_models.race_control import RaceControlEventDB
    from datetime import datetime

    db_row = RaceControlEventDB(
        meeting_key=1275, session_key=9850, date=datetime(2025, 11, 30, 16, 3, 27),
        category="Flag", message="GREEN LIGHT", scope="Track", sector=None, driver_number=None, flag=None,
    )
    monkeypatch.setattr(race_control, "check_race_control_events_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(race_control, "get_race_control_events_from_db", AsyncMock(return_value=[db_row]))
    fetch_openf1 = AsyncMock()
    monkeypatch.setattr(race_control, "fetch_race_control_events_from_openf1", fetch_openf1)

    result = await race_control.get_race_control_events_for_session(9850)

    assert len(result) == 1
    assert result[0].message == "GREEN LIGHT"
    fetch_openf1.assert_not_awaited()
