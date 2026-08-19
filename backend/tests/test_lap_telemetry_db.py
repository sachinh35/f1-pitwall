"""Unit tests for db/lap_telemetry_db.py (mocked DB, same pattern as test_live_persistence.py)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from db import lap_telemetry_db


def _mock_db(monkeypatch: pytest.MonkeyPatch, fetchrow_result):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_result)

    class _FakeConnCtx:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(lap_telemetry_db.DatabaseManager, "get_connection", MagicMock(return_value=_FakeConnCtx()))
    return mock_conn


@pytest.mark.asyncio
async def test_get_lap_telemetry_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_db(monkeypatch, None)
    result = await lap_telemetry_db.get_lap_telemetry(9850, 1, 10)
    assert result is None


@pytest.mark.asyncio
async def test_get_lap_telemetry_maps_row_to_dataclass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_row = {
        "session_key": 9850, "driver_number": 1, "lap_number": 10,
        "dt_ms": [0, 250, 500], "speed": [300, 305, 310], "rpm": [11000, 11200, 11400],
        "gear": [8, 8, 8], "throttle_pct": [100, 100, 95], "brake_pct": [0, 0, 0], "drs": [12, 12, 0],
    }
    _mock_db(monkeypatch, fake_row)
    result = await lap_telemetry_db.get_lap_telemetry(9850, 1, 10)
    assert result is not None
    assert result.driver_number == 1
    assert result.speed == [300, 305, 310]
    assert result.drs == [12, 12, 0]


@pytest.mark.asyncio
async def test_get_lap_position_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_db(monkeypatch, None)
    result = await lap_telemetry_db.get_lap_position(9850, 1, 10)
    assert result is None


@pytest.mark.asyncio
async def test_get_lap_position_maps_row_to_dataclass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_row = {
        "session_key": 9850, "driver_number": 1, "lap_number": 10,
        "dt_ms": [0, 300], "x": [-1416, -1300], "y": [-99, -50], "z": [154, 155],
        "status": ["OnTrack", "OnTrack"],
    }
    _mock_db(monkeypatch, fake_row)
    result = await lap_telemetry_db.get_lap_position(9850, 1, 10)
    assert result is not None
    assert result.x == [-1416, -1300]
    assert result.status == ["OnTrack", "OnTrack"]
