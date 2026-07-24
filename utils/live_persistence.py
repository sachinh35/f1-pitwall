"""
Warm-tier persistence for live/replayed sessions.

Writes one row per driver per completed lap to `lap_data` (extended with the
derived aggregate columns), `lap_telemetry`, and `lap_car_position` - full
resolution, one row per lap, not one row per raw sample (see the product
investigation artifact's storage-tier design for why). Triggered by the
reducer's lap-boundary detection; always called as a detached background
task, never on the live broadcast's critical path.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from utils.database import DatabaseManager
from utils.session_state import CompletedLap

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_rc_timestamp(value: Any) -> Optional[datetime]:
    """F1's RaceControlMessages Utc field has no fractional seconds or 'Z' suffix (e.g. '2025-11-30T15:57:04')."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None


async def persist_completed_lap(session_key: int, meeting_key: int, lap: CompletedLap) -> None:
    """Upsert one driver's completed lap into lap_data, lap_telemetry, and lap_car_position."""
    async with DatabaseManager.get_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO lap_data (
                    meeting_key, session_key, driver_number, lap_number, lap_duration,
                    avg_speed_kmh, max_speed_kmh, avg_throttle_pct, drs_active_pct
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (session_key, driver_number, lap_number) DO UPDATE SET
                    lap_duration = EXCLUDED.lap_duration,
                    avg_speed_kmh = EXCLUDED.avg_speed_kmh,
                    max_speed_kmh = EXCLUDED.max_speed_kmh,
                    avg_throttle_pct = EXCLUDED.avg_throttle_pct,
                    drs_active_pct = EXCLUDED.drs_active_pct,
                    updated_at = CURRENT_TIMESTAMP
                """,
                meeting_key, session_key, lap.driver_number, lap.lap_number, lap.lap_duration_seconds,
                lap.aggregates.avg_speed_kmh, lap.aggregates.max_speed_kmh,
                lap.aggregates.avg_throttle_pct, lap.aggregates.drs_active_pct,
            )

            telemetry = lap.telemetry
            if telemetry.speed:
                await conn.execute(
                    """
                    INSERT INTO lap_telemetry (
                        session_key, driver_number, lap_number, sample_count,
                        dt_ms, speed, rpm, gear, throttle_pct, brake_pct, drs
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (session_key, driver_number, lap_number) DO UPDATE SET
                        sample_count = EXCLUDED.sample_count,
                        dt_ms = EXCLUDED.dt_ms,
                        speed = EXCLUDED.speed,
                        rpm = EXCLUDED.rpm,
                        gear = EXCLUDED.gear,
                        throttle_pct = EXCLUDED.throttle_pct,
                        brake_pct = EXCLUDED.brake_pct,
                        drs = EXCLUDED.drs
                    """,
                    session_key, lap.driver_number, lap.lap_number, len(telemetry.speed),
                    telemetry.dt_ms, telemetry.speed, telemetry.rpm, telemetry.gear,
                    telemetry.throttle_pct, telemetry.brake_pct, telemetry.drs,
                )

            if telemetry.x:
                await conn.execute(
                    """
                    INSERT INTO lap_car_position (session_key, driver_number, lap_number, dt_ms, x, y, z, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (session_key, driver_number, lap_number) DO UPDATE SET
                        dt_ms = EXCLUDED.dt_ms,
                        x = EXCLUDED.x,
                        y = EXCLUDED.y,
                        z = EXCLUDED.z,
                        status = EXCLUDED.status
                    """,
                    session_key, lap.driver_number, lap.lap_number,
                    telemetry.position_dt_ms, telemetry.x, telemetry.y, telemetry.z, telemetry.position_status,
                )

    logger.info(
        "Persisted completed lap session_key=%s driver=%s lap=%s (telemetry=%d position=%d samples)",
        session_key, lap.driver_number, lap.lap_number, len(telemetry.speed), len(telemetry.x),
    )


async def persist_weather_snapshot(session_key: int, weather: Dict[str, Any]) -> None:
    """Insert one WeatherData tick into weather_snapshots. Weather fields arrive as strings on the raw feed."""
    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO weather_snapshots (
                session_key, ts, air_temp, track_temp, humidity, pressure, rainfall, wind_speed, wind_direction
            ) VALUES ($1, CURRENT_TIMESTAMP, $2, $3, $4, $5, $6, $7, $8)
            """,
            session_key,
            _to_float(weather.get("AirTemp")),
            _to_float(weather.get("TrackTemp")),
            _to_float(weather.get("Humidity")),
            _to_float(weather.get("Pressure")),
            _to_int(weather.get("Rainfall")),
            _to_float(weather.get("WindSpeed")),
            _to_int(weather.get("WindDirection")),
        )


async def persist_race_control_entry(session_key: int, meeting_key: Optional[int], entry: Dict[str, Any]) -> None:
    """Insert one live RaceControlMessages entry into race_control_events (the same table the historical
    OpenF1-backed path reads/writes - Garage Mode and a live/replayed session share one table)."""
    if meeting_key is None:
        logger.warning("Dropping race control persist for session_key=%s - meeting_key not yet known", session_key)
        return

    date_value = _parse_rc_timestamp(entry.get("Utc"))
    if date_value is None:
        logger.warning("Dropping race control entry with unparseable Utc=%r", entry.get("Utc"))
        return

    driver_number_raw = entry.get("RacingNumber")
    driver_number = _to_int(driver_number_raw)
    scope = "Driver" if driver_number is not None else "Track"

    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO race_control_events (meeting_key, session_key, date, category, message, scope, sector, driver_number, flag)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            meeting_key, session_key, date_value,
            entry.get("Category") or "Other",
            entry.get("Message", ""),
            scope,
            _to_int(entry.get("Sector")),
            driver_number,
            entry.get("Flag"),
        )
