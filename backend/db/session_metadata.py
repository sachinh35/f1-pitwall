"""
Fetch session metadata (circuit/location/date/session type) and the driver
roster actually entered for a session, from OpenF1.

Used by the live/replay pipeline the moment a session's SessionInfo message
reveals its session_key: the SignalR feed itself never carries this
information (DriverList only ever has a grid "Line" number - see
driverRoster.ts on the frontend for where that was confirmed), so it's
fetched out-of-band, once per session, from OpenF1's REST API instead.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from constants.openf1_api_endpoints import DRIVERS_API_URL, LAPS_API_URL, SESSIONS_API_URL
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import F1Session
from common.http_client import fetch_json

logger = logging.getLogger(__name__)

_OPENF1_TIMEOUT_SECONDS: float = 10.0


async def fetch_session_metadata(session_key: int) -> Optional[F1Session]:
    """Fetch this session's circuit/location/date/type from OpenF1.

    Returns None on any failure (network error, or OpenF1 not having indexed
    this session yet) - callers treat that as "not available right now", not
    a fatal error, since it must never take down the live pipeline.
    """
    try:
        payload = await fetch_json(
            SESSIONS_API_URL, params={"session_key": session_key}, timeout=_OPENF1_TIMEOUT_SECONDS
        )
    except Exception:
        logger.exception("Failed to fetch session metadata for session_key=%s", session_key)
        return None
    if not payload:
        logger.warning("OpenF1 returned no session metadata for session_key=%s", session_key)
        return None
    return F1Session(**payload[0])


async def fetch_total_laps(session_key: int) -> Optional[int]:
    """Resolve the race's total scheduled lap count as the highest lap_number OpenF1's
    /v1/laps has recorded for this session.

    F1's live SignalR feed never carries this - confirmed by enumerating every LapCount
    message across a full captured race: every one ever contains only {"CurrentLap": N},
    never a total (also confirmed SessionInfo/SessionData carry nothing lap-count-related
    either). This is necessarily retrospective: for a genuinely live/future session, OpenF1
    won't have any lap records yet, so this correctly returns None until laps have actually
    been recorded - same "can't trust OpenF1 for live data" constraint ConfirmedRosterEntry
    already works around for the driver roster, just with no workaround available here since
    there's no equivalent of a human confirming a race's total lap count up front.
    """
    try:
        payload = await fetch_json(LAPS_API_URL, params={"session_key": session_key}, timeout=_OPENF1_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Failed to fetch laps for total-laps resolution, session_key=%s", session_key)
        return None
    if not payload:
        return None
    lap_numbers = [lap["lap_number"] for lap in payload if lap.get("lap_number") is not None]
    return max(lap_numbers) if lap_numbers else None


async def fetch_driver_roster(session_key: int) -> List[DriverInfo]:
    """Fetch the drivers actually entered for this specific session (not meeting).

    Session-scoped rather than meeting-scoped on purpose: a reserve/substitute
    driver can change the entered roster from one session to the next within
    the same race weekend. Returns an empty list on any failure.
    """
    try:
        payload = await fetch_json(
            DRIVERS_API_URL, params={"session_key": session_key}, timeout=_OPENF1_TIMEOUT_SECONDS
        )
    except Exception:
        logger.exception("Failed to fetch driver roster for session_key=%s", session_key)
        return []
    return [DriverInfo(**driver) for driver in payload]
