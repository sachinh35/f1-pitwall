"""Pydantic response models for the lap-to-lap telemetry comparison endpoint."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class LapTraceResponse(BaseModel):
    """One driver's one lap, resampled onto a shared distance axis."""
    driver_number: int
    lap_number: int
    distance_m: List[float]
    speed_kmh: List[float]
    throttle_pct: List[float]
    brake_pct: List[float]
    acceleration_ms2: List[float]


class CornerResponse(BaseModel):
    distance_m: float
    apex_speed_kmh: float


class DeltaTraceResponse(BaseModel):
    distance_m: List[float]
    delta_seconds: List[float] = Field(..., description="Positive = driver B losing time to driver A at this point")
    corners: List[CornerResponse]


class LapComparisonResponse(BaseModel):
    session_key: int
    driver_a: LapTraceResponse
    driver_b: LapTraceResponse
    delta: DeltaTraceResponse
