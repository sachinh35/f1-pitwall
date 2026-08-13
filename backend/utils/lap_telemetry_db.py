"""
Read access for lap_telemetry and lap_car_position - the full-resolution,
per-driver-per-lap arrays written by utils/live_persistence.py at lap
boundaries. Nothing has read these back until now (Milestone 6 only wrote
to them); this is what the lap-comparison feature fetches from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from utils.database import DatabaseManager


@dataclass
class LapTelemetryRow:
    session_key: int
    driver_number: int
    lap_number: int
    dt_ms: List[int]
    speed: List[int]
    rpm: List[int]
    gear: List[int]
    throttle_pct: List[int]
    brake_pct: List[int]
    drs: List[int]


@dataclass
class LapPositionRow:
    session_key: int
    driver_number: int
    lap_number: int
    dt_ms: List[int]
    x: List[int]
    y: List[int]
    z: List[int]
    status: List[str]


async def get_lap_telemetry(session_key: int, driver_number: int, lap_number: int) -> Optional[LapTelemetryRow]:
    async with DatabaseManager.get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_key, driver_number, lap_number, dt_ms, speed, rpm, gear, throttle_pct, brake_pct, drs
            FROM lap_telemetry
            WHERE session_key = $1 AND driver_number = $2 AND lap_number = $3
            """,
            session_key, driver_number, lap_number,
        )
        if row is None:
            return None
        return LapTelemetryRow(
            session_key=row["session_key"],
            driver_number=row["driver_number"],
            lap_number=row["lap_number"],
            dt_ms=list(row["dt_ms"]),
            speed=list(row["speed"]),
            rpm=list(row["rpm"]),
            gear=list(row["gear"]),
            throttle_pct=list(row["throttle_pct"]),
            brake_pct=list(row["brake_pct"]),
            drs=list(row["drs"]),
        )


async def get_lap_position(session_key: int, driver_number: int, lap_number: int) -> Optional[LapPositionRow]:
    async with DatabaseManager.get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_key, driver_number, lap_number, dt_ms, x, y, z, status
            FROM lap_car_position
            WHERE session_key = $1 AND driver_number = $2 AND lap_number = $3
            """,
            session_key, driver_number, lap_number,
        )
        if row is None:
            return None
        return LapPositionRow(
            session_key=row["session_key"],
            driver_number=row["driver_number"],
            lap_number=row["lap_number"],
            dt_ms=list(row["dt_ms"]),
            x=list(row["x"]),
            y=list(row["y"]),
            z=list(row["z"]),
            status=list(row["status"]),
        )
