"""
Utility functions for fetching race/session metadata and results from OpenF1.
"""
from __future__ import annotations

import logging
from typing import List

from api_pydantic_models.races import RaceInfo
from api_pydantic_models.race_sesssions import EnrichedF1SessionResult
from constants.openf1_api_endpoints import DRIVERS_API_URL, SESSION_RESULTS_API_URL, SESSIONS_API_URL
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import GetF1SessionResultResponse, GetF1SessionsResponse
from common.http_client import fetch_json

logger = logging.getLogger(__name__)

_OPENF1_TIMEOUT_SECONDS: float = 10.0


async def get_races_by_year(year: int) -> List[RaceInfo]:
    """Fetch all sessions for a given year from OpenF1, sorted by location."""
    try:
        payload = await fetch_json(SESSIONS_API_URL, params={"year": year}, timeout=_OPENF1_TIMEOUT_SECONDS)
        all_races = GetF1SessionsResponse(sessions=payload)
        race_info = [
            RaceInfo(
                session_key=s.session_key,
                location=s.location,
                session_name=s.session_name,
                country_code=s.country_code,
            )
            for s in all_races.sessions
        ]
        return sorted(race_info, key=lambda x: x.location)
    except Exception:
        logger.exception("Failed to fetch races for year=%s", year)
        raise


async def get_results_by_session_key(session_key: int) -> List[EnrichedF1SessionResult]:
    """Fetch session results from OpenF1, enriched with driver info."""
    try:
        logger.info("Invoking GetSessionResponse for session_key=%s", session_key)
        results_payload = await fetch_json(
            SESSION_RESULTS_API_URL, params={"session_key": session_key}, timeout=_OPENF1_TIMEOUT_SECONDS
        )
        validated_response = GetF1SessionResultResponse(session_result=results_payload)

        # Sort by DNF status (DNFs at the back) and then by position
        sorted_results = sorted(
            validated_response.session_result,
            key=lambda x: (x.dnf, x.position is None, x.position),
        )

        driver_numbers = [result.driver_number for result in sorted_results]
        if not driver_numbers:
            return []

        # Fetch all driver info in a single API call
        driver_payload = await fetch_json(
            DRIVERS_API_URL,
            params={"driver_number": driver_numbers, "session_key": session_key},
            timeout=_OPENF1_TIMEOUT_SECONDS,
        )
        driver_info_list = [DriverInfo(**driver) for driver in driver_payload]
        driver_info_map = {driver.driver_number: driver for driver in driver_info_list}

        enriched_results: List[EnrichedF1SessionResult] = []
        for result in sorted_results:
            driver_info = driver_info_map.get(result.driver_number)
            if driver_info:
                enriched_results.append(
                    EnrichedF1SessionResult(
                        dnf=result.dnf,
                        dns=result.dns,
                        dsq=result.dsq,
                        driver_number=result.driver_number,
                        number_of_laps=result.number_of_laps,
                        meeting_key=result.meeting_key,
                        session_key=result.session_key,
                        duration=result.duration,
                        gap_to_leader=result.gap_to_leader,
                        position=result.position,
                        full_name=driver_info.full_name,
                        name_acronym=driver_info.name_acronym,
                        first_name=driver_info.first_name,
                        last_name=driver_info.last_name,
                        country_code=driver_info.country_code,
                    )
                )

        return enriched_results
    except Exception:
        logger.exception("Failed to fetch session results for session_key=%s", session_key)
        raise
