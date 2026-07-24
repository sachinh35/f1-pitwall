"""
Generic cache-first fetch orchestration.

Captures the "check DB -> if missing, fetch from source, convert, insert,
re-read" pipeline that used to be copy-pasted across lap_data.py, stints.py
and race_control.py, each with only naming differences.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, List, TypeVar

SourceModel = TypeVar("SourceModel")
DbModel = TypeVar("DbModel")

logger = logging.getLogger(__name__)


async def get_or_fetch(
    *,
    check_exists: Callable[[], Awaitable[bool]],
    get_from_db: Callable[[], Awaitable[List[DbModel]]],
    fetch_from_source: Callable[[], Awaitable[List[SourceModel]]],
    convert_to_db: Callable[[SourceModel], DbModel],
    insert_batch: Callable[[List[DbModel]], Awaitable[None]],
    log_label: str,
) -> List[DbModel]:
    """
    Serve from DB if present; otherwise fetch from source (e.g. OpenF1),
    convert, persist, then re-read from DB so the caller always gets back
    exactly what's now stored (including any ON CONFLICT resolution from insert).

    Every argument is a zero-arg callable with its session/driver filtering
    already bound by the caller (e.g. via functools.partial), so this helper
    stays agnostic to each domain's specific key shape.
    """
    if await check_exists():
        logger.info("%s served from DB cache", log_label)
        return await get_from_db()

    logger.info("%s not found in DB, fetching from source", log_label)
    source_items = await fetch_from_source()
    db_models = [convert_to_db(item) for item in source_items]

    if db_models:
        logger.info("Inserting %d %s records into DB", len(db_models), log_label)
        await insert_batch(db_models)

    return await get_from_db()
