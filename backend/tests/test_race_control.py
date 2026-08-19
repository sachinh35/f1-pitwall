"""
Covers the parts of db/race_control.py not already exercised by
test_lap_data.py's cache-hit smoke test: the OpenF1 fetch leg and the
scope-inference logic in convert_openf1_to_db_model.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from openf1_pydantic_models.f1_race_control import F1RaceControlEvent
from db import race_control


@pytest.mark.asyncio
async def test_fetch_race_control_events_from_openf1_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "date": "2025-11-30T16:03:27",
            "session_key": 9850,
            "meeting_key": 1275,
            "category": "Flag",
            "message": "GREEN LIGHT",
            "flag": "GREEN",
        }
    ]
    monkeypatch.setattr(race_control, "fetch_json", AsyncMock(return_value=payload))

    result = await race_control.fetch_race_control_events_from_openf1(9850)

    assert len(result) == 1
    assert isinstance(result[0], F1RaceControlEvent)
    assert result[0].message == "GREEN LIGHT"


@pytest.mark.asyncio
async def test_fetch_race_control_events_from_openf1_returns_empty_list_when_no_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(race_control, "fetch_json", AsyncMock(return_value=[]))
    result = await race_control.fetch_race_control_events_from_openf1(9850)
    assert result == []


def _openf1_event(**overrides) -> F1RaceControlEvent:
    defaults = dict(
        date=datetime(2025, 11, 30, 16, 3, 27, tzinfo=timezone.utc),
        session_key=9850,
        meeting_key=1275,
        category="Flag",
        message="GREEN LIGHT",
        scope=None,
        sector=None,
        driver_number=None,
        flag="GREEN",
    )
    defaults.update(overrides)
    return F1RaceControlEvent(**defaults)


def test_convert_infers_driver_scope_when_driver_number_present() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event(driver_number=1))
    assert db_event.scope == "Driver"


def test_convert_infers_sector_scope_when_sector_present_and_no_driver() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event(sector=3))
    assert db_event.scope == "Sector"


def test_convert_infers_track_scope_when_neither_driver_nor_sector_present() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event())
    assert db_event.scope == "Track"


def test_convert_preserves_explicit_scope_over_inference() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event(scope="Track", driver_number=1))
    assert db_event.scope == "Track"


def test_convert_defaults_missing_category_to_other() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event(category=None))
    assert db_event.category == "Other"


def test_convert_db_to_response_model_formats_datetime() -> None:
    db_event = race_control.convert_openf1_to_db_model(_openf1_event())
    response = race_control.convert_db_to_response_model(db_event)
    assert response.date == db_event.date.isoformat()


@pytest.mark.asyncio
async def test_get_race_control_events_for_session_cache_miss_fetches_and_inserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api_pydantic_models.race_control import RaceControlEventDB

    db_row = RaceControlEventDB(
        meeting_key=1275, session_key=9850, date=datetime(2025, 11, 30, 16, 3, 27),
        category="Flag", message="GREEN LIGHT", scope="Track", sector=None, driver_number=None, flag=None,
    )
    monkeypatch.setattr(race_control, "check_race_control_events_exists", AsyncMock(return_value=False))
    monkeypatch.setattr(
        race_control, "fetch_race_control_events_from_openf1", AsyncMock(return_value=[_openf1_event()])
    )
    insert_batch = AsyncMock()
    monkeypatch.setattr(race_control, "insert_race_control_events_batch", insert_batch)
    monkeypatch.setattr(race_control, "get_race_control_events_from_db", AsyncMock(return_value=[db_row]))

    result = await race_control.get_race_control_events_for_session(9850)

    insert_batch.assert_awaited_once()
    assert len(result) == 1
    assert result[0].message == "GREEN LIGHT"
