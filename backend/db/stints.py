"""
Utility functions for fetching and managing stints data.
Cache-first: check DB, otherwise fetch from OpenF1 API and store.
"""
from __future__ import annotations

import logging
from functools import partial
from typing import List

from api_pydantic_models.stints import StintDB, StintResponse
from constants.openf1_api_endpoints import STINTS_API_URL
from openf1_pydantic_models.f1_stints import F1Stint
from db.cache_first_fetch import get_or_fetch
from db.database import (
    check_session_stints_exists,
    get_stints_from_db,
    insert_stints_batch,
)
from common.http_client import fetch_json

logger = logging.getLogger(__name__)


async def fetch_stints_from_openf1(session_key: int) -> List[F1Stint]:
    """Fetch stint data from OpenF1 API for a given session."""
    payload = await fetch_json(STINTS_API_URL, params={"session_key": session_key})
    stints = [F1Stint(**item) for item in payload]
    logger.info("Fetched %d stints from OpenF1 for session_key=%s", len(stints), session_key)
    return stints


def convert_openf1_to_db_model(openf1: F1Stint) -> StintDB:
    """Convert OpenF1 API stint model to database model."""
    return StintDB(
        meeting_key=openf1.meeting_key,
        session_key=openf1.session_key,
        driver_number=openf1.driver_number,
        stint_number=openf1.stint_number,
        lap_start=openf1.lap_start,
        lap_end=openf1.lap_end,
        compound=openf1.compound,
        tyre_age_at_start=openf1.tyre_age_at_start,
    )


def convert_db_to_response_model(db: StintDB) -> StintResponse:
    """Convert database model to API response model."""
    return StintResponse(
        meeting_key=db.meeting_key,
        session_key=db.session_key,
        driver_number=db.driver_number,
        stint_number=db.stint_number,
        lap_start=db.lap_start,
        lap_end=db.lap_end,
        compound=db.compound,
        tyre_age_at_start=db.tyre_age_at_start,
    )


async def get_stints_for_session(session_key: int) -> List[StintResponse]:
    """Get stints for a session, cache-first (DB, else OpenF1)."""
    db_rows = await get_or_fetch(
        check_exists=partial(check_session_stints_exists, session_key),
        get_from_db=partial(get_stints_from_db, session_key),
        fetch_from_source=partial(fetch_stints_from_openf1, session_key),
        convert_to_db=convert_openf1_to_db_model,
        insert_batch=insert_stints_batch,
        log_label=f"Stints (session_key={session_key})",
    )
    return [convert_db_to_response_model(r) for r in db_rows]
