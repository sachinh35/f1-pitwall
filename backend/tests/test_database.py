"""
Unit tests for utils/database.py - DatabaseManager's pool lifecycle plus the lap_data/
stints/race_control_events DB helper functions. All asyncpg I/O is mocked; no real
Postgres connection is made.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_pydantic_models.lap_data import LapDataDB
from api_pydantic_models.race_control import RaceControlEventDB
from api_pydantic_models.stints import StintDB
from utils import database
from utils.database import DatabaseManager


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    DatabaseManager._pool = None
    yield
    DatabaseManager._pool = None


class _FakeConnection:
    def __init__(self):
        self.fetchval = AsyncMock(return_value=0)
        self.fetch = AsyncMock(return_value=[])
        self.executemany = AsyncMock()


class _FakePool:
    def __init__(self, connection: _FakeConnection):
        self._connection = connection
        self.close = AsyncMock()

    @asynccontextmanager
    async def acquire(self):
        yield self._connection


# ---- DatabaseManager pool lifecycle ----

@pytest.mark.asyncio
async def test_get_pool_creates_pool_once_using_config_connection_string() -> None:
    fake_pool = _FakePool(_FakeConnection())
    with patch.object(database.asyncpg, "create_pool", new=AsyncMock(return_value=fake_pool)) as mock_create, \
         patch.object(database.DatabaseConfig, "get_async_connection_string", return_value="postgresql://x"):
        pool1 = await DatabaseManager.get_pool()
        pool2 = await DatabaseManager.get_pool()

    assert pool1 is pool2 is fake_pool
    mock_create.assert_called_once_with("postgresql://x", min_size=1, max_size=10, command_timeout=60)


@pytest.mark.asyncio
async def test_close_pool_closes_and_resets_singleton() -> None:
    fake_pool = _FakePool(_FakeConnection())
    DatabaseManager._pool = fake_pool

    await DatabaseManager.close_pool()

    fake_pool.close.assert_called_once()
    assert DatabaseManager._pool is None


@pytest.mark.asyncio
async def test_close_pool_is_a_noop_when_no_pool_exists() -> None:
    assert DatabaseManager._pool is None
    await DatabaseManager.close_pool()  # must not raise
    assert DatabaseManager._pool is None


@pytest.mark.asyncio
async def test_get_connection_yields_an_acquired_connection() -> None:
    fake_connection = _FakeConnection()
    fake_pool = _FakePool(fake_connection)
    with patch.object(DatabaseManager, "get_pool", new=AsyncMock(return_value=fake_pool)):
        async with DatabaseManager.get_connection() as conn:
            assert conn is fake_connection


def _patched_connection(fake_connection: _FakeConnection):
    fake_pool = _FakePool(fake_connection)
    return patch.object(DatabaseManager, "get_pool", new=AsyncMock(return_value=fake_pool))


# ---- lap_data helpers ----

@pytest.mark.asyncio
async def test_check_session_data_exists_true_when_all_drivers_found() -> None:
    conn = _FakeConnection()
    conn.fetchval.return_value = 2
    with _patched_connection(conn):
        result = await database.check_session_data_exists(123, [1, 44])
    assert result is True


@pytest.mark.asyncio
async def test_check_session_data_exists_false_when_some_drivers_missing() -> None:
    conn = _FakeConnection()
    conn.fetchval.return_value = 1
    with _patched_connection(conn):
        result = await database.check_session_data_exists(123, [1, 44])
    assert result is False


@pytest.mark.asyncio
async def test_get_lap_data_from_db_maps_rows_to_models() -> None:
    row = {
        "id": 1, "meeting_key": 10, "session_key": 123, "driver_number": 1, "lap_number": 1,
        "date_start": None, "duration_sector_1": None, "duration_sector_2": None, "duration_sector_3": None,
        "lap_duration": 90.5, "i1_speed": None, "i2_speed": None, "st_speed": None, "is_pit_out_lap": False,
        "segments_sector_1": None, "segments_sector_2": None, "segments_sector_3": None,
        "created_at": None, "updated_at": None,
    }
    conn = _FakeConnection()
    conn.fetch.return_value = [row]
    with _patched_connection(conn):
        result = await database.get_lap_data_from_db(123, [1])
    assert len(result) == 1
    assert isinstance(result[0], LapDataDB)
    assert result[0].lap_duration == 90.5


@pytest.mark.asyncio
async def test_insert_lap_data_batch_skips_query_when_empty() -> None:
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_lap_data_batch([])
    conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_insert_lap_data_batch_executes_for_nonempty_list() -> None:
    lap = LapDataDB(meeting_key=10, session_key=123, driver_number=1, lap_number=1, is_pit_out_lap=False)
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_lap_data_batch([lap])
    conn.executemany.assert_called_once()


# ---- stints helpers ----

@pytest.mark.asyncio
async def test_check_session_stints_exists() -> None:
    conn = _FakeConnection()
    conn.fetchval.return_value = True
    with _patched_connection(conn):
        assert await database.check_session_stints_exists(123) is True


@pytest.mark.asyncio
async def test_get_stints_from_db_maps_rows_to_models() -> None:
    row = {
        "id": 1, "meeting_key": 10, "session_key": 123, "driver_number": 1, "stint_number": 1,
        "lap_start": 1, "lap_end": 20, "compound": "MEDIUM", "tyre_age_at_start": 0,
        "created_at": None, "updated_at": None,
    }
    conn = _FakeConnection()
    conn.fetch.return_value = [row]
    with _patched_connection(conn):
        result = await database.get_stints_from_db(123)
    assert len(result) == 1
    assert isinstance(result[0], StintDB)
    assert result[0].compound == "MEDIUM"


@pytest.mark.asyncio
async def test_insert_stints_batch_skips_query_when_empty() -> None:
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_stints_batch([])
    conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_insert_stints_batch_executes_for_nonempty_list() -> None:
    stint = StintDB(meeting_key=10, session_key=123, driver_number=1, stint_number=1, lap_start=1, lap_end=20)
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_stints_batch([stint])
    conn.executemany.assert_called_once()


# ---- race control events helpers ----

@pytest.mark.asyncio
async def test_check_race_control_events_exists() -> None:
    conn = _FakeConnection()
    conn.fetchval.return_value = False
    with _patched_connection(conn):
        assert await database.check_race_control_events_exists(123) is False


@pytest.mark.asyncio
async def test_get_race_control_events_from_db_maps_rows_and_formats_timestamps() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = {
        "id": 1, "meeting_key": 10, "session_key": 123, "date": now, "category": "Flag",
        "message": "GREEN LIGHT", "scope": None, "sector": None, "driver_number": None, "flag": "GREEN",
        "created_at": now, "updated_at": None,
    }
    conn = _FakeConnection()
    conn.fetch.return_value = [row]
    with _patched_connection(conn):
        result = await database.get_race_control_events_from_db(123)
    assert len(result) == 1
    assert isinstance(result[0], RaceControlEventDB)
    assert result[0].created_at == now.isoformat()
    assert result[0].updated_at is None


@pytest.mark.asyncio
async def test_insert_race_control_events_batch_skips_query_when_empty() -> None:
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_race_control_events_batch([])
    conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_insert_race_control_events_batch_executes_for_nonempty_list() -> None:
    event = RaceControlEventDB(
        meeting_key=10, session_key=123, date=datetime.now(timezone.utc), category="Flag", message="GREEN LIGHT"
    )
    conn = _FakeConnection()
    with _patched_connection(conn):
        await database.insert_race_control_events_batch([event])
    conn.executemany.assert_called_once()
