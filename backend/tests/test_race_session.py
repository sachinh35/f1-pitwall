"""Unit tests for db/race_session.py - both OpenF1-backed functions, with fetch_json
mocked (no real network calls)."""
from unittest.mock import AsyncMock

import pytest

from db import race_session


@pytest.mark.asyncio
async def test_get_races_by_year_sorts_by_location(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "circuit_key": 1, "circuit_short_name": "Losail", "country_code": "QAT", "country_key": 1,
            "country_name": "Qatar", "date_end": "2025-11-30T18:00:00", "date_start": "2025-11-30T15:00:00",
            "gmt_offset": "+03:00", "location": "Zzz Town", "meeting_key": 1275, "session_key": 9850,
            "session_name": "Race", "session_type": "Race", "year": 2025,
        },
        {
            "circuit_key": 2, "circuit_short_name": "Yas Marina", "country_code": "UAE", "country_key": 2,
            "country_name": "UAE", "date_end": "2025-12-07T18:00:00", "date_start": "2025-12-07T15:00:00",
            "gmt_offset": "+04:00", "location": "Abu Dhabi", "meeting_key": 1276, "session_key": 9851,
            "session_name": "Race", "session_type": "Race", "year": 2025,
        },
    ]
    monkeypatch.setattr(race_session, "fetch_json", AsyncMock(return_value=payload))

    result = await race_session.get_races_by_year(2025)

    assert [r.location for r in result] == ["Abu Dhabi", "Zzz Town"]


@pytest.mark.asyncio
async def test_get_races_by_year_logs_and_reraises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(race_session, "fetch_json", AsyncMock(side_effect=RuntimeError("openf1 down")))

    with pytest.raises(RuntimeError, match="openf1 down"):
        await race_session.get_races_by_year(2025)


_RESULT = {
    "dnf": False, "dns": False, "dsq": False, "driver_number": 1, "number_of_laps": 58,
    "meeting_key": 1275, "session_key": 9850, "duration": 5400.1, "gap_to_leader": 0, "position": 1,
}
_DRIVER = {
    "meeting_key": 1275, "session_key": 9850, "driver_number": 1, "broadcast_name": "M VERSTAPPEN",
    "full_name": "Max Verstappen", "name_acronym": "VER", "team_name": "Red Bull Racing",
    "team_colour": "3671C6", "first_name": "Max", "last_name": "Verstappen", "headshot_url": None,
    "country_code": "NED",
}


@pytest.mark.asyncio
async def test_get_results_by_session_key_enriches_with_driver_info(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_mock = AsyncMock(side_effect=[[_RESULT], [_DRIVER]])
    monkeypatch.setattr(race_session, "fetch_json", fetch_mock)

    result = await race_session.get_results_by_session_key(9850)

    assert len(result) == 1
    assert result[0].full_name == "Max Verstappen"
    assert result[0].name_acronym == "VER"
    assert fetch_mock.await_count == 2


@pytest.mark.asyncio
async def test_get_results_by_session_key_drops_results_with_no_matching_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_driver = {**_DRIVER, "driver_number": 44}
    fetch_mock = AsyncMock(side_effect=[[_RESULT], [other_driver]])
    monkeypatch.setattr(race_session, "fetch_json", fetch_mock)

    result = await race_session.get_results_by_session_key(9850)

    assert result == []


@pytest.mark.asyncio
async def test_get_results_by_session_key_returns_empty_list_with_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(race_session, "fetch_json", fetch_mock)

    result = await race_session.get_results_by_session_key(9850)

    assert result == []
    # Only the results call should happen - no point fetching driver info for zero drivers.
    fetch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_results_by_session_key_logs_and_reraises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(race_session, "fetch_json", AsyncMock(side_effect=RuntimeError("openf1 down")))

    with pytest.raises(RuntimeError, match="openf1 down"):
        await race_session.get_results_by_session_key(9850)


@pytest.mark.asyncio
async def test_get_results_by_session_key_sorts_dnf_to_the_back(monkeypatch: pytest.MonkeyPatch) -> None:
    p1 = {**_RESULT, "driver_number": 1, "position": 1, "dnf": False}
    dnf_driver = {**_RESULT, "driver_number": 44, "position": None, "dnf": True}
    driver1 = _DRIVER
    driver44 = {**_DRIVER, "driver_number": 44}
    fetch_mock = AsyncMock(side_effect=[[dnf_driver, p1], [driver1, driver44]])
    monkeypatch.setattr(race_session, "fetch_json", fetch_mock)

    result = await race_session.get_results_by_session_key(9850)

    assert [r.driver_number for r in result] == [1, 44]
