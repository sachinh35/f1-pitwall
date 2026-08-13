"""Covers the parts of utils/lap_data.py not exercised by test_lap_data.py's
get_lap_data_for_session equivalence test: the OpenF1 fetch leg and the
DB<->OpenF1 conversion helpers."""
from unittest.mock import AsyncMock

import pytest

from openf1_pydantic_models.f1_laps import F1LapData
from utils import lap_data


@pytest.mark.asyncio
async def test_fetch_laps_from_openf1_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "meeting_key": 1275, "session_key": 9850, "driver_number": 1, "lap_number": 1,
            "lap_duration": 87.15, "is_pit_out_lap": False,
        }
    ]
    monkeypatch.setattr(lap_data, "fetch_json", AsyncMock(return_value=payload))

    result = await lap_data.fetch_laps_from_openf1(9850)

    assert len(result) == 1
    assert isinstance(result[0], F1LapData)
    assert result[0].lap_duration == 87.15


def test_convert_openf1_to_db_model_maps_all_fields() -> None:
    openf1_lap = F1LapData(
        meeting_key=1275, session_key=9850, driver_number=1, lap_number=1,
        lap_duration=87.15, is_pit_out_lap=True, i1_speed=300,
    )
    db_lap = lap_data.convert_openf1_to_db_model(openf1_lap)
    assert db_lap.driver_number == 1
    assert db_lap.lap_duration == 87.15
    assert db_lap.is_pit_out_lap is True
    assert db_lap.i1_speed == 300


def test_convert_db_to_response_model_maps_all_fields() -> None:
    from api_pydantic_models.lap_data import LapDataDB

    db_lap = LapDataDB(
        meeting_key=1275, session_key=9850, driver_number=1, lap_number=1,
        lap_duration=87.15, is_pit_out_lap=False,
    )
    response = lap_data.convert_db_to_response_model(db_lap)
    assert response.driver_number == 1
    assert response.lap_duration == 87.15
