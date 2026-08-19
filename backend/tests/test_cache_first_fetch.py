"""Unit tests for db/cache_first_fetch.py."""
from typing import List
from unittest.mock import AsyncMock

import pytest

from db.cache_first_fetch import get_or_fetch


@pytest.mark.asyncio
async def test_cache_hit_serves_from_db_without_fetching_source() -> None:
    check_exists = AsyncMock(return_value=True)
    get_from_db = AsyncMock(return_value=["db-row-1", "db-row-2"])
    fetch_from_source = AsyncMock()
    convert_to_db = lambda item: item  # noqa: E731 - trivial identity for this test
    insert_batch = AsyncMock()

    result = await get_or_fetch(
        check_exists=check_exists,
        get_from_db=get_from_db,
        fetch_from_source=fetch_from_source,
        convert_to_db=convert_to_db,
        insert_batch=insert_batch,
        log_label="test",
    )

    assert result == ["db-row-1", "db-row-2"]
    check_exists.assert_awaited_once()
    get_from_db.assert_awaited_once()
    fetch_from_source.assert_not_awaited()
    insert_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_fetches_converts_inserts_then_rereads_db() -> None:
    check_exists = AsyncMock(return_value=False)
    # First call (wouldn't happen) vs. the post-insert re-read - only called once, after insert.
    get_from_db = AsyncMock(return_value=["db-row-after-insert"])
    fetch_from_source = AsyncMock(return_value=["source-item-1", "source-item-2"])
    convert_calls: List[str] = []

    def convert_to_db(item: str) -> str:
        convert_calls.append(item)
        return f"converted-{item}"

    insert_batch = AsyncMock()

    result = await get_or_fetch(
        check_exists=check_exists,
        get_from_db=get_from_db,
        fetch_from_source=fetch_from_source,
        convert_to_db=convert_to_db,
        insert_batch=insert_batch,
        log_label="test",
    )

    assert result == ["db-row-after-insert"]
    fetch_from_source.assert_awaited_once()
    assert convert_calls == ["source-item-1", "source-item-2"]
    insert_batch.assert_awaited_once_with(["converted-source-item-1", "converted-source-item-2"])
    get_from_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_miss_with_empty_source_skips_insert() -> None:
    check_exists = AsyncMock(return_value=False)
    get_from_db = AsyncMock(return_value=[])
    fetch_from_source = AsyncMock(return_value=[])
    insert_batch = AsyncMock()

    result = await get_or_fetch(
        check_exists=check_exists,
        get_from_db=get_from_db,
        fetch_from_source=fetch_from_source,
        convert_to_db=lambda item: item,  # noqa: E731
        insert_batch=insert_batch,
        log_label="test",
    )

    assert result == []
    insert_batch.assert_not_awaited()
