"""Covers utils/stints.py's OpenF1 fetch leg, not exercised by test_lap_data.py's
get_stints_for_session cache-miss test (which mocks fetch_stints_from_openf1 itself)."""
from unittest.mock import AsyncMock

import pytest

from openf1_pydantic_models.f1_stints import F1Stint
from utils import stints


@pytest.mark.asyncio
async def test_fetch_stints_from_openf1_parses_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "meeting_key": 1275, "session_key": 9850, "driver_number": 1, "stint_number": 1,
            "lap_start": 1, "lap_end": 20, "compound": "MEDIUM", "tyre_age_at_start": 0,
        }
    ]
    monkeypatch.setattr(stints, "fetch_json", AsyncMock(return_value=payload))

    result = await stints.fetch_stints_from_openf1(9850)

    assert len(result) == 1
    assert isinstance(result[0], F1Stint)
    assert result[0].compound == "MEDIUM"
