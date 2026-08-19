"""Unit tests for db/team_driver_pool_db.py."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from db import team_driver_pool_db


def _mock_db(monkeypatch: pytest.MonkeyPatch, rows: list) -> AsyncMock:
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=rows)

    class _FakeConnCtx:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(team_driver_pool_db.DatabaseManager, "get_connection", MagicMock(return_value=_FakeConnCtx()))
    return mock_conn


@pytest.mark.asyncio
async def test_get_team_driver_pool_maps_rows_to_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"team_name": "McLaren", "driver_number": 1, "tla": "NOR", "full_name": "Lando Norris", "is_reserve": False},
        {"team_name": "McLaren", "driver_number": None, "tla": None, "full_name": "Pato O'Ward", "is_reserve": True},
    ]
    mock_conn = _mock_db(monkeypatch, rows)

    result = await team_driver_pool_db.get_team_driver_pool(2026)

    mock_conn.fetch.assert_awaited_once()
    args = mock_conn.fetch.call_args.args
    assert args[1] == 2026  # season_year param

    assert len(result) == 2
    assert result[0].team_name == "McLaren"
    assert result[0].driver_number == 1
    assert result[0].is_reserve is False
    assert result[1].driver_number is None
    assert result[1].is_reserve is True


@pytest.mark.asyncio
async def test_get_team_driver_pool_empty_for_unknown_season(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_db(monkeypatch, [])
    result = await team_driver_pool_db.get_team_driver_pool(1999)
    assert result == []
