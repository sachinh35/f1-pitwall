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
from utils.time_utils import normalize_datetime


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
    """Mirrors the `team_radio` table (migrations/0004_weather_radio.sql,
    extended by 0009_team_radio_analysis.sql and 0013_team_radio_qualifying_part.sql)."""
    id: Optional[int] = None
    session_key: int
    driver_number: int
    lap_number: Optional[int] = None
    qualifying_part: Optional[str] = None
    ts: datetime
    audio_path: Optional[str] = None
    transcript: Optional[str] = None
    status: RadioClipStatus = RadioClipStatus.PENDING
    error: Optional[str] = None
    transcribed_at: Optional[datetime] = None
    # Gemini-classified, set once analysis completes (see utils/radio_analysis.py) - all
    # None until then, and speaker_role in particular is an LLM inference, not ground
    # truth, since F1's raw feed carries no speaker/diarization info at all.
    speaker_role: Optional[str] = None
    is_notable: Optional[bool] = None
    notable_reason: Optional[str] = None


async def insert_pending(
    session_key: int,
    driver_number: int,
    lap_number: Optional[int],
    ts: datetime,
    capture_path: str,
    qualifying_part: Optional[str] = None,
) -> Optional[int]:
    """Insert a new team_radio row in `pending` state, returning its id - or None if this
    exact capture (session_key, capture_path) already has a row, meaning it was already
    downloaded/transcribed/analyzed by a previous run (see uq_team_radio_session_capture_path
    - this was a real bug: without it, every re-simulation/re-tail of the same archive
    re-ran the full pipeline, including Whisper and Gemini calls, for every capture from
    scratch). The caller must skip the rest of its pipeline entirely on None, not just skip
    the insert - see utils/team_radio_pipeline.py.

    `ts` comes from F1's raw TeamRadio.Captures[].Utc, parsed tz-aware (see
    session_state._parse_utc); `team_radio.ts` is a plain TIMESTAMP column, so this
    must be normalized first - previously wasn't, which meant every single capture
    crashed here (asyncpg.exceptions.DataError) before a row was ever inserted,
    confirmed against a real replay run.
    """
    async with DatabaseManager.get_connection() as conn:
        return await conn.fetchval(
            """
            INSERT INTO team_radio (session_key, driver_number, lap_number, qualifying_part, ts, capture_path, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (session_key, capture_path) DO NOTHING
            RETURNING id
            """,
            session_key, driver_number, lap_number, qualifying_part,
            normalize_datetime(ts), capture_path, RadioClipStatus.PENDING.value,
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


async def mark_analyzed(row_id: int, speaker_role: str, is_notable: bool, notable_reason: Optional[str]) -> None:
    """Record the Gemini classification for an already-transcribed clip. Deliberately does not
    touch `status` - a failed/skipped analysis must never regress an otherwise-successful
    transcription back to a non-done state (see utils/team_radio_pipeline.py)."""
    await _update(row_id, speaker_role=speaker_role, is_notable=is_notable, notable_reason=notable_reason)


async def get_for_session(session_key: int) -> List[TeamRadioDB]:
    """All radio clips for a session, oldest first - used both for a live session's initial load and for
    browsing a finished session's radio history (same table, same query path, live or historical)."""
    async with DatabaseManager.get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_key, driver_number, lap_number, qualifying_part, ts, audio_path, transcript,
                   status, error, transcribed_at, speaker_role, is_notable, notable_reason
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
                qualifying_part=row["qualifying_part"],
                ts=row["ts"],
                audio_path=row["audio_path"],
                transcript=row["transcript"],
                status=RadioClipStatus(row["status"]),
                error=row["error"],
                transcribed_at=row["transcribed_at"],
                speaker_role=row["speaker_role"],
                is_notable=row["is_notable"],
                notable_reason=row["notable_reason"],
            )
            for row in rows
        ]
