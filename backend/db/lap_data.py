"""
Utility functions for fetching and managing lap data.
Handles the logic for checking DB cache, fetching from OpenF1 API, and storing data.
"""
from __future__ import annotations

import logging
from functools import partial
from typing import List

from api_pydantic_models.lap_data import LapDataDB, LapDataResponse
from constants.openf1_api_endpoints import LAPS_API_URL
from openf1_pydantic_models.f1_laps import F1LapData
from db.cache_first_fetch import get_or_fetch
from db.database import (
    check_session_data_exists,
    get_lap_data_from_db,
    insert_lap_data_batch,
)
from common.http_client import fetch_json
from common.time_utils import normalize_datetime

logger = logging.getLogger(__name__)


async def fetch_laps_from_openf1(session_key: int) -> List[F1LapData]:
    """Fetch lap data from OpenF1 API for a given session."""
    payload = await fetch_json(LAPS_API_URL, params={"session_key": session_key})
    laps = [F1LapData(**lap) for lap in payload]
    logger.info("Fetched %d lap records from OpenF1 for session_key=%s", len(laps), session_key)
    return laps


def convert_openf1_to_db_model(openf1_lap: F1LapData) -> LapDataDB:
    """Convert OpenF1 API lap data model to database model, normalizing timestamps."""
    return LapDataDB(
        meeting_key=openf1_lap.meeting_key,
        session_key=openf1_lap.session_key,
        driver_number=openf1_lap.driver_number,
        lap_number=openf1_lap.lap_number,
        date_start=normalize_datetime(openf1_lap.date_start),
        duration_sector_1=openf1_lap.duration_sector_1,
        duration_sector_2=openf1_lap.duration_sector_2,
        duration_sector_3=openf1_lap.duration_sector_3,
        lap_duration=openf1_lap.lap_duration,
        i1_speed=openf1_lap.i1_speed,
        i2_speed=openf1_lap.i2_speed,
        st_speed=openf1_lap.st_speed,
        is_pit_out_lap=openf1_lap.is_pit_out_lap,
        segments_sector_1=openf1_lap.segments_sector_1,
        segments_sector_2=openf1_lap.segments_sector_2,
        segments_sector_3=openf1_lap.segments_sector_3,
    )


def convert_db_to_response_model(db_lap: LapDataDB) -> LapDataResponse:
    """Convert database model to API response model."""
    return LapDataResponse(
        meeting_key=db_lap.meeting_key,
        session_key=db_lap.session_key,
        driver_number=db_lap.driver_number,
        lap_number=db_lap.lap_number,
        date_start=db_lap.date_start,
        duration_sector_1=db_lap.duration_sector_1,
        duration_sector_2=db_lap.duration_sector_2,
        duration_sector_3=db_lap.duration_sector_3,
        lap_duration=db_lap.lap_duration,
        i1_speed=db_lap.i1_speed,
        i2_speed=db_lap.i2_speed,
        st_speed=db_lap.st_speed,
        is_pit_out_lap=db_lap.is_pit_out_lap,
        segments_sector_1=db_lap.segments_sector_1,
        segments_sector_2=db_lap.segments_sector_2,
        segments_sector_3=db_lap.segments_sector_3,
    )


async def get_lap_data_for_session(
    session_key: int,
    driver_numbers: List[int],
) -> List[LapDataResponse]:
    """
    Get lap data for a session and drivers, cache-first (DB, else OpenF1).
    """
    db_laps = await get_or_fetch(
        check_exists=partial(check_session_data_exists, session_key, driver_numbers),
        get_from_db=partial(get_lap_data_from_db, session_key, driver_numbers),
        fetch_from_source=partial(fetch_laps_from_openf1, session_key),
        convert_to_db=convert_openf1_to_db_model,
        insert_batch=insert_lap_data_batch,
        log_label=f"Lap data (session_key={session_key})",
    )

    return [
        convert_db_to_response_model(lap)
        for lap in db_laps
        if lap.driver_number in driver_numbers
    ]
