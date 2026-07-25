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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import F1Session
from utils.database import DatabaseManager
from utils.session_state import CompletedLap, QualifyingResultEntry
from utils.time_utils import normalize_datetime

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
                    avg_speed_kmh, max_speed_kmh, avg_throttle_pct, drs_active_pct, gap_to_ahead_seconds,
                    qualifying_part
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (session_key, driver_number, lap_number) DO UPDATE SET
                    lap_duration = EXCLUDED.lap_duration,
                    avg_speed_kmh = EXCLUDED.avg_speed_kmh,
                    max_speed_kmh = EXCLUDED.max_speed_kmh,
                    avg_throttle_pct = EXCLUDED.avg_throttle_pct,
                    drs_active_pct = EXCLUDED.drs_active_pct,
                    gap_to_ahead_seconds = EXCLUDED.gap_to_ahead_seconds,
                    qualifying_part = EXCLUDED.qualifying_part,
                    updated_at = CURRENT_TIMESTAMP
                """,
                meeting_key, session_key, lap.driver_number, lap.lap_number, lap.lap_duration_seconds,
                lap.aggregates.avg_speed_kmh, lap.aggregates.max_speed_kmh,
                lap.aggregates.avg_throttle_pct, lap.aggregates.drs_active_pct, lap.gap_to_ahead_seconds,
                lap.qualifying_part,
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


async def mark_lap_deleted(session_key: int, driver_number: int, lap_number: int) -> None:
    """
    Flag a previously-persisted lap_data row is_deleted=true - triggered by
    SessionState._apply_race_control parsing a RaceControlMessages deletion entry (see
    session_state.DeletedLap). Deliberately a no-op UPDATE (not upsert) if the row doesn't
    exist yet: the lap-completion message and the race-control deletion message can arrive
    in either order in principle, but in practice the deletion always follows completion by
    several seconds (confirmed live) - if this ever did race ahead, the flag would simply be
    lost rather than crash, which is an acceptable trade-off for a display-only annotation.
    """
    async with DatabaseManager.get_connection() as conn:
        result = await conn.execute(
            """
            UPDATE lap_data SET is_deleted = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE session_key = $1 AND driver_number = $2 AND lap_number = $3
            """,
            session_key, driver_number, lap_number,
        )
    if result == "UPDATE 0":
        logger.warning(
            "mark_lap_deleted: no lap_data row for session_key=%s driver=%s lap=%s (race-control "
            "deletion arrived before the lap was persisted?)",
            session_key, driver_number, lap_number,
        )


async def persist_qualifying_results(
    session_key: int, meeting_key: Optional[int], results: List[QualifyingResultEntry]
) -> None:
    """Upsert one qualifying segment's final standings (see SessionState._snapshot_qualifying_results) -
    a durable record retrievable directly from Postgres afterwards instead of replaying/recomputing
    from the raw stream. Idempotent (ON CONFLICT DO UPDATE) since SessionStatus "Finalised" can arrive
    more than once (guarded upstream too - see SessionState._final_results_captured)."""
    if not results:
        return
    async with DatabaseManager.get_connection() as conn:
        await conn.executemany(
            """
            INSERT INTO qualifying_results (
                session_key, meeting_key, driver_number, qualifying_part,
                position, best_lap_seconds, gap_to_leader_seconds, eliminated
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (session_key, qualifying_part, driver_number) DO UPDATE SET
                position = EXCLUDED.position,
                best_lap_seconds = EXCLUDED.best_lap_seconds,
                gap_to_leader_seconds = EXCLUDED.gap_to_leader_seconds,
                eliminated = EXCLUDED.eliminated,
                recorded_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    session_key, meeting_key, r.driver_number, r.qualifying_part,
                    r.position, r.best_lap_seconds, r.gap_to_leader_seconds, r.eliminated,
                )
                for r in results
            ],
        )
    logger.info(
        "Persisted qualifying_results session_key=%s part=%s (%d drivers)",
        session_key, results[0].qualifying_part, len(results),
    )


async def persist_weather_snapshot(session_key: int, weather: Dict[str, Any], ts: Optional[datetime] = None) -> None:
    """
    Insert one WeatherData tick into weather_snapshots. Weather fields arrive as strings on the raw feed.

    `ts` should be the real event time (StateDiff.event_time - from the raw archive's own
    capture timestamp during replay/tail, or "now" for a genuinely live message), not
    insertion time - the two only coincide for a truly live message. Falls back to "now"
    only if the caller has nothing better. ON CONFLICT DO NOTHING makes this idempotent
    against a session being re-tailed/replayed from scratch (see uq_weather_snapshots_session_ts
    - a real bug this fixes: every backend restart used to re-insert the entire weather
    history for the session).
    """
    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO weather_snapshots (
                session_key, ts, air_temp, track_temp, humidity, pressure, rainfall, wind_speed, wind_direction
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (session_key, ts) DO NOTHING
            """,
            session_key,
            normalize_datetime(ts) or datetime.now(timezone.utc).replace(tzinfo=None),
            _to_float(weather.get("AirTemp")),
            _to_float(weather.get("TrackTemp")),
            _to_float(weather.get("Humidity")),
            _to_float(weather.get("Pressure")),
            _to_int(weather.get("Rainfall")),
            _to_float(weather.get("WindSpeed")),
            _to_int(weather.get("WindDirection")),
        )


async def persist_race_control_entry(session_key: int, meeting_key: Optional[int], entry: Dict[str, Any]) -> None:
    """
    Insert one live RaceControlMessages entry into race_control_events (the same table the
    historical OpenF1-backed path reads/writes - Garage Mode and a live/replayed session
    share one table).

    `entry["index"]` is F1's own per-message index for this session (see
    SessionState._apply_race_control - already used there to dedupe within one process's
    lifetime); stored as message_index and used for ON CONFLICT DO NOTHING so re-tailing/
    replaying a session from scratch doesn't re-insert every message again (a real bug this
    fixes - see uq_race_control_session_message_index). Historical OpenF1-sourced rows have
    no such index and store NULL there, which never collides with anything.
    """
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
    message_index = _to_int(entry.get("index"))

    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO race_control_events (
                meeting_key, session_key, date, category, message, scope, sector, driver_number, flag, message_index
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (session_key, message_index) DO NOTHING
            """,
            meeting_key, session_key, date_value,
            entry.get("Category") or "Other",
            entry.get("Message", ""),
            scope,
            _to_int(entry.get("Sector")),
            driver_number,
            entry.get("Flag"),
            message_index,
        )


def _to_naive_utc(value: datetime) -> datetime:
    """OpenF1 returns timezone-aware timestamps; `sessions.date_start`/`date_end` are plain
    TIMESTAMP (no tz) columns, and asyncpg's timestamp codec rejects an aware datetime outright."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def persist_session_metadata(session: F1Session) -> None:
    """Upsert this session's circuit/location/date/type into `sessions` - fetched once from OpenF1
    the moment SessionInfo reveals a session_key, since the live feed itself never carries it."""
    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                session_key, meeting_key, session_name, session_type, circuit_key, circuit_short_name,
                country_code, country_name, location, date_start, date_end, gmt_offset, year
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (session_key) DO UPDATE SET
                meeting_key = EXCLUDED.meeting_key,
                session_name = EXCLUDED.session_name,
                session_type = EXCLUDED.session_type,
                circuit_key = EXCLUDED.circuit_key,
                circuit_short_name = EXCLUDED.circuit_short_name,
                country_code = EXCLUDED.country_code,
                country_name = EXCLUDED.country_name,
                location = EXCLUDED.location,
                date_start = EXCLUDED.date_start,
                date_end = EXCLUDED.date_end,
                gmt_offset = EXCLUDED.gmt_offset,
                year = EXCLUDED.year
            """,
            session.session_key, session.meeting_key, session.session_name, session.session_type,
            session.circuit_key, session.circuit_short_name, session.country_code, session.country_name,
            session.location, _to_naive_utc(session.date_start), _to_naive_utc(session.date_end),
            session.gmt_offset, session.year,
        )
    logger.info("Persisted session metadata session_key=%s location=%s", session.session_key, session.location)


async def persist_total_laps(session_key: int, total_laps: int) -> None:
    """Record the resolved total race-lap count against an already-persisted session row
    (see utils.session_metadata.fetch_total_laps for why this is a separate, later write
    rather than part of persist_session_metadata's OpenF1-sourced F1Session fields)."""
    async with DatabaseManager.get_connection() as conn:
        await conn.execute(
            "UPDATE sessions SET total_laps = $2 WHERE session_key = $1", session_key, total_laps
        )
    logger.info("Persisted total_laps session_key=%s total_laps=%s", session_key, total_laps)


async def persist_driver_roster(session_key: int, drivers: List[DriverInfo]) -> None:
    """Upsert the driver roster actually entered for this session into `driver_roster`."""
    async with DatabaseManager.get_connection() as conn:
        async with conn.transaction():
            for driver in drivers:
                await conn.execute(
                    """
                    INSERT INTO driver_roster (
                        session_key, driver_number, broadcast_name, full_name, name_acronym,
                        team_name, team_colour, first_name, last_name, headshot_url, country_code
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (session_key, driver_number) DO UPDATE SET
                        broadcast_name = EXCLUDED.broadcast_name,
                        full_name = EXCLUDED.full_name,
                        name_acronym = EXCLUDED.name_acronym,
                        team_name = EXCLUDED.team_name,
                        team_colour = EXCLUDED.team_colour,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        headshot_url = EXCLUDED.headshot_url,
                        country_code = EXCLUDED.country_code
                    """,
                    session_key, driver.driver_number, driver.broadcast_name, driver.full_name,
                    driver.name_acronym, driver.team_name, driver.team_colour, driver.first_name,
                    driver.last_name, driver.headshot_url, driver.country_code,
                )
    logger.info("Persisted driver roster session_key=%s count=%d", session_key, len(drivers))


async def persist_confirmed_driver_roster(session_key: int, entries: List[ConfirmedRosterEntry]) -> None:
    """Upsert a user-confirmed pre-race lineup into `driver_roster` - the same table the OpenF1-backed
    fetch writes to, just without the extra OpenF1-only fields (broadcast_name, headshot_url, etc.),
    which stay NULL here since a manually-confirmed entry never has them."""
    async with DatabaseManager.get_connection() as conn:
        async with conn.transaction():
            for entry in entries:
                await conn.execute(
                    """
                    INSERT INTO driver_roster (session_key, driver_number, full_name, name_acronym, team_name)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (session_key, driver_number) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        name_acronym = EXCLUDED.name_acronym,
                        team_name = EXCLUDED.team_name
                    """,
                    session_key, entry.driver_number, entry.full_name, entry.tla, entry.team_name,
                )
    logger.info("Persisted confirmed driver roster session_key=%s count=%d", session_key, len(entries))
