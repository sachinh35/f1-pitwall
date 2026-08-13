"""Unit tests for scripts/migrate.py's DB-touching half (apply_pending_migrations, _main)
- pure file-discovery/version-parsing logic is covered separately in test_migrate.py."""
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts import migrate
from utils.database import DatabaseManager


class _FakeConnection:
    def __init__(self, already_applied_versions=()):
        self.execute = AsyncMock()
        self.fetch = AsyncMock(return_value=[{"version": v} for v in already_applied_versions])
        self.executed_sql: list[str] = []
        self.execute.side_effect = lambda sql, *a, **kw: self.executed_sql.append(sql)

    @asynccontextmanager
    async def transaction(self):
        yield


@asynccontextmanager
async def _fake_get_connection(conn: _FakeConnection):
    yield conn


@pytest.mark.asyncio
async def test_apply_pending_migrations_applies_new_files_in_order(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id int);")
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE b (id int);")

    conn = _FakeConnection(already_applied_versions=[])
    with patch.object(DatabaseManager, "get_connection", return_value=_fake_get_connection(conn)):
        applied = await migrate.apply_pending_migrations(tmp_path)

    assert applied == [1, 2]
    assert any("CREATE TABLE a" in sql for sql in conn.executed_sql)
    assert any("CREATE TABLE b" in sql for sql in conn.executed_sql)


@pytest.mark.asyncio
async def test_apply_pending_migrations_skips_already_applied(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id int);")
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE b (id int);")

    conn = _FakeConnection(already_applied_versions=[1])
    with patch.object(DatabaseManager, "get_connection", return_value=_fake_get_connection(conn)):
        applied = await migrate.apply_pending_migrations(tmp_path)

    assert applied == [2]
    assert not any("CREATE TABLE a" in sql for sql in conn.executed_sql)


@pytest.mark.asyncio
async def test_apply_pending_migrations_returns_empty_when_up_to_date(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (id int);")

    conn = _FakeConnection(already_applied_versions=[1])
    with patch.object(DatabaseManager, "get_connection", return_value=_fake_get_connection(conn)):
        applied = await migrate.apply_pending_migrations(tmp_path)

    assert applied == []


@pytest.mark.asyncio
async def test_main_applies_and_closes_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "apply_pending_migrations", AsyncMock(return_value=[1, 2]))
    close_pool = AsyncMock()
    monkeypatch.setattr(DatabaseManager, "close_pool", close_pool)

    await migrate._main()

    close_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_handles_no_pending_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "apply_pending_migrations", AsyncMock(return_value=[]))
    close_pool = AsyncMock()
    monkeypatch.setattr(DatabaseManager, "close_pool", close_pool)

    await migrate._main()  # must not raise

    close_pool.assert_awaited_once()
