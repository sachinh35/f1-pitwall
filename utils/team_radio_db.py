"""
DB access for team-radio clips.

This is a live-only concept with no OpenF1/historical equivalent, so unlike
lap_data/stints/race_control it doesn't fit the cache-first fetch pattern in
utils/cache_first_fetch.py - it's an insert-then-repeatedly-update state
machine (see utils/team_radio_pipeline.py), not a batch cache read.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel

from utils.database import DatabaseManager


class RadioClipStatus(str, Enum):
    """Mirrors the state machine in utils/team_radio_pipeline.py."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    DONE = "done"
    FAILED_DOWNLOAD = "failed_download"
    FAILED_TRANSCRIPTION = "failed_transcription"


class TeamRadioDB(BaseModel):
    """Mirrors the `team_radio` table (migrations/0004_weather_radio.sql)."""
    id: Optional[int] = None
    session_key: int
    driver_number: int
    lap_number: Optional[int] = None
    ts: datetime
    audio_path: Optional[str] = None
    transcript: Optional[str] = None
    status: RadioClipStatus = RadioClipStatus.PENDING
    error: Optional[str] = None
    transcribed_at: Optional[datetime] = None


async def insert_pending(
    session_key: int,
    driver_number: int,
    lap_number: Optional[int],
    ts: datetime,
) -> int:
    """Insert a new team_radio row in `pending` state, returning its id."""
    async with DatabaseManager.get_connection() as conn:
        return await conn.fetchval(
            """
            INSERT INTO team_radio (session_key, driver_number, lap_number, ts, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            session_key, driver_number, lap_number, ts, RadioClipStatus.PENDING.value,
        )


async def _update(row_id: int, **fields: Any) -> None:
    """Generic `UPDATE team_radio SET ... WHERE id = row_id`, built from arbitrary column->value kwargs.

    Column names come only from this module's own calls below (never from
    external input), so building the SET clause from kwarg names is safe.
    """
    if not fields:
        return
    columns = list(fields.keys())
    set_clause = ", ".join(f"{column} = ${i + 2}" for i, column in enumerate(columns))
    query = f"UPDATE team_radio SET {set_clause} WHERE id = $1"
    async with DatabaseManager.get_connection() as conn:
        await conn.execute(query, row_id, *(fields[column] for column in columns))


async def mark_downloading(row_id: int) -> None:
    await _update(row_id, status=RadioClipStatus.DOWNLOADING.value)


async def mark_downloaded(row_id: int, audio_path: str) -> None:
    await _update(row_id, status=RadioClipStatus.DOWNLOADED.value, audio_path=audio_path)


async def mark_failed_download(row_id: int, error: str) -> None:
    await _update(row_id, status=RadioClipStatus.FAILED_DOWNLOAD.value, error=error)


async def mark_transcribing(row_id: int) -> None:
    await _update(row_id, status=RadioClipStatus.TRANSCRIBING.value)


async def mark_done(row_id: int, transcript: str) -> None:
    await _update(
        row_id,
        status=RadioClipStatus.DONE.value,
        transcript=transcript,
        transcribed_at=datetime.now(timezone.utc).replace(tzinfo=None),  # naive, matching the TIMESTAMP column
    )


async def mark_failed_transcription(row_id: int, error: str) -> None:
    await _update(row_id, status=RadioClipStatus.FAILED_TRANSCRIPTION.value, error=error)


async def get_for_session(session_key: int) -> List[TeamRadioDB]:
    """All radio clips for a session, oldest first - used both for a live session's initial load and for
    browsing a finished session's radio history (same table, same query path, live or historical)."""
    async with DatabaseManager.get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_key, driver_number, lap_number, ts, audio_path, transcript, status, error, transcribed_at
            FROM team_radio
            WHERE session_key = $1
            ORDER BY ts
            """,
            session_key,
        )
        return [
            TeamRadioDB(
                id=row["id"],
                session_key=row["session_key"],
                driver_number=row["driver_number"],
                lap_number=row["lap_number"],
                ts=row["ts"],
                audio_path=row["audio_path"],
                transcript=row["transcript"],
                status=RadioClipStatus(row["status"]),
                error=row["error"],
                transcribed_at=row["transcribed_at"],
            )
            for row in rows
        ]
