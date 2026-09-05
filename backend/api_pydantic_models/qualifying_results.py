"""
Pydantic models for the qualifying-results API - a durable per-segment (Q1/Q2/Q3)
final standings snapshot, persisted the instant each segment ends (see
live/session_state.py's QualifyingResultEntry and db/live_persistence.py).
"""
from typing import Dict, List, Optional

from pydantic import BaseModel


class QualifyingResultEntryResponse(BaseModel):
    """One driver's final standing for one qualifying segment."""
    driver_number: int
    position: Optional[int] = None
    best_lap_seconds: Optional[float] = None
    gap_to_leader_seconds: Optional[float] = None
    eliminated: bool


class GetQualifyingResultsResponse(BaseModel):
    """Response model for getting a session's captured qualifying-segment results.

    Keyed by segment ("Q1"/"Q2"/"Q3") rather than a flat list so the frontend can
    render one card per completed segment without grouping client-side - a segment
    absent from this dict simply hasn't ended yet (or this isn't a qualifying session).
    """
    session_key: int
    results: Dict[str, List[QualifyingResultEntryResponse]]
