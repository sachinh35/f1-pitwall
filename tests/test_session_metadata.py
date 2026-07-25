"""Unit tests for utils/session_metadata.py."""
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from utils import session_metadata

_RAW_SESSION = {
    "circuit_key": 63,
    "circuit_short_name": "Losail",
    "country_code": "QAT",
    "country_key": 10,
    "country_name": "Qatar",
    "date_end": "2025-11-30T18:00:00",
    "date_start": "2025-11-30T16:00:00",
    "gmt_offset": "03:00:00",
    "location": "Lusail",
    "meeting_key": 1275,
    "session_key": 9850,
    "session_name": "Race",
    "session_type": "Race",
    "year": 2025,
}

_RAW_DRIVER = {
    "meeting_key": 1275,
    "session_key": 9850,
    "driver_number": 1,
    "broadcast_name": "M VERSTAPPEN",
    "full_name": "Max Verstappen",
    "name_acronym": "VER",
    "team_name": "Red Bull Racing",
    "team_colour": "3671C6",
    "first_name": "Max",
    "last_name": "Verstappen",
    "headshot_url": "https://example.com/ver.png",
    "country_code": "NED",
}


@pytest.mark.asyncio
async def test_fetch_session_metadata_parses_first_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_metadata, "fetch_json", AsyncMock(return_value=[_RAW_SESSION]))

    result = await session_metadata.fetch_session_metadata(9850)

    assert result is not None
    assert result.session_key == 9850
    assert result.location == "Lusail"
    assert result.date_start == datetime(2025, 11, 30, 16, 0, 0)


@pytest.mark.asyncio
async def test_fetch_session_metadata_returns_none_on_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_metadata, "fetch_json", AsyncMock(return_value=[]))

    assert await session_metadata.fetch_session_metadata(9850) is None


@pytest.mark.asyncio
async def test_fetch_session_metadata_returns_none_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_metadata, "fetch_json", AsyncMock(side_effect=httpx.TransportError("boom"))
    )

    assert await session_metadata.fetch_session_metadata(9850) is None


@pytest.mark.asyncio
async def test_fetch_driver_roster_parses_all_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_metadata, "fetch_json", AsyncMock(return_value=[_RAW_DRIVER]))

    drivers = await session_metadata.fetch_driver_roster(9850)

    assert len(drivers) == 1
    assert drivers[0].driver_number == 1
    assert drivers[0].name_acronym == "VER"


@pytest.mark.asyncio
async def test_fetch_driver_roster_returns_empty_list_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_metadata, "fetch_json", AsyncMock(side_effect=httpx.TransportError("boom"))
    )

    assert await session_metadata.fetch_driver_roster(9850) == []
