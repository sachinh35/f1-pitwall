"""
Utility functions for fetching and managing race control events.
Handles the logic for checking DB cache, fetching from OpenF1 API, and storing data.
"""
from __future__ import annotations

import logging
from datetime import datetime
from functools import partial
from typing import List

from api_pydantic_models.race_control import RaceControlEventDB, RaceControlEventResponse
from constants.openf1_api_endpoints import RACE_CONTROL_API_URL
from openf1_pydantic_models.f1_race_control import F1RaceControlEvent
from utils.cache_first_fetch import get_or_fetch
from utils.database import (
    check_race_control_events_exists,
    get_race_control_events_from_db,
    insert_race_control_events_batch,
)
from utils.http_client import fetch_json
from utils.time_utils import normalize_datetime

logger = logging.getLogger(__name__)


async def fetch_race_control_events_from_openf1(session_key: int) -> List[F1RaceControlEvent]:
    """
    Fetch race control events from OpenF1 API. An empty response is valid
    (not every session has race control events) and returns an empty list.
    """
    payload = await fetch_json(RACE_CONTROL_API_URL, params={"session_key": session_key})
    if not payload:
        logger.warning("OpenF1 API returned empty race control events for session_key=%s", session_key)
        return []
    events = [F1RaceControlEvent(**event) for event in payload]
    logger.info("Fetched %d race control events from OpenF1 for session_key=%s", len(events), session_key)
    return events


def convert_openf1_to_db_model(openf1_event: F1RaceControlEvent) -> RaceControlEventDB:
    """Convert OpenF1 API race control event model to database model."""
    scope = openf1_event.scope
    if not scope:
        if openf1_event.driver_number is not None:
            scope = "Driver"
        elif openf1_event.sector is not None:
            scope = "Sector"
        else:
            scope = "Track"

    return RaceControlEventDB(
        meeting_key=openf1_event.meeting_key,
        session_key=openf1_event.session_key,
        date=normalize_datetime(openf1_event.date),
        category=openf1_event.category or "Other",
        message=openf1_event.message,
        scope=scope,
        sector=openf1_event.sector,
        driver_number=openf1_event.driver_number,
        flag=openf1_event.flag,
    )


def convert_db_to_response_model(db_event: RaceControlEventDB) -> RaceControlEventResponse:
    """Convert database model to API response model."""
    return RaceControlEventResponse(
        session_key=db_event.session_key,
        date=db_event.date.isoformat() if isinstance(db_event.date, datetime) else str(db_event.date),
        category=db_event.category,
        message=db_event.message,
        scope=db_event.scope,
        sector=db_event.sector,
        driver_number=db_event.driver_number,
        flag=db_event.flag,
    )


async def get_race_control_events_for_session(session_key: int) -> List[RaceControlEventResponse]:
    """Get race control events for a session, cache-first (DB, else OpenF1)."""
    db_events = await get_or_fetch(
        check_exists=partial(check_race_control_events_exists, session_key),
        get_from_db=partial(get_race_control_events_from_db, session_key),
        fetch_from_source=partial(fetch_race_control_events_from_openf1, session_key),
        convert_to_db=convert_openf1_to_db_model,
        insert_batch=insert_race_control_events_batch,
        log_label=f"Race control events (session_key={session_key})",
    )
    return [convert_db_to_response_model(event) for event in db_events]
