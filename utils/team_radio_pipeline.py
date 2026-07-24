"""
Team radio pipeline: download a captured clip, transcribe it locally with
Whisper, persist the transcript - all as a detached background task that
never blocks the live broadcast path (same rule as every other Warm-tier
write in this project; see the product investigation artifact's "write path"
section for the full rationale).

State machine:  pending -> downloading -> downloaded -> transcribing -> done
                        \\                          \\
                         -> failed_download          -> failed_transcription
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional

from utils import team_radio_db, whisper_transcriber
from utils.http_client import download_binary
from utils.session_state import RadioCapture

logger = logging.getLogger(__name__)

# Based on the convention used by FastF1 and other F1 live-timing tools for
# this feed's static content host. NOT independently confirmed by a
# successful fetch against this project - the saved F1TV token is expired,
# so this has only been exercised against the failure path so far. A driver
# hitting a fresh token should verify this resolves correctly.
F1_STATIC_CONTENT_BASE_URL: str = "https://livetiming.formula1.com/static"

AUDIO_CACHE_DIR: Path = Path("audio_cache")

# Invoked after the clip is downloaded (playable) and again once it's
# transcribed (caption ready). Owned by whoever wires up the SSE broadcast
# (Milestone 6) - this module doesn't need to know SSE exists.
BroadcastCallback = Callable[[str, int], Awaitable[None]]


def resolve_audio_url(relative_path: str) -> str:
    """Resolve a TeamRadio message's relative `Path` into a fetchable URL."""
    return f"{F1_STATIC_CONTENT_BASE_URL}/{relative_path}"


def local_audio_path(session_key: int, capture: RadioCapture, cache_dir: Path = AUDIO_CACHE_DIR) -> Path:
    """Where a clip's audio is cached on disk once downloaded."""
    filename = capture.path.rsplit("/", 1)[-1]
    return cache_dir / str(session_key) / filename


def web_relative_audio_path(session_key: int, capture: RadioCapture) -> str:
    """
    The path stored in `team_radio.audio_path` and served by main.py's `/audio`
    static mount - relative to AUDIO_CACHE_DIR (the mount root), not the local
    disk path `local_audio_path()` returns, since the frontend shouldn't need
    to know the cache directory's name is "audio_cache".
    """
    filename = capture.path.rsplit("/", 1)[-1]
    return f"{session_key}/{filename}"


async def process_radio_capture(
    session_key: int,
    capture: RadioCapture,
    auth_headers: Optional[Dict[str, str]] = None,
    on_downloaded: Optional[BroadcastCallback] = None,
    on_transcribed: Optional[BroadcastCallback] = None,
) -> None:
    """
    Run one radio clip through the full download -> transcribe pipeline.

    Meant to be scheduled as a detached `asyncio.create_task(...)` per
    capture, never awaited inline on the live broadcast path. Every failure
    is caught, logged, and recorded on the row rather than re-raised - one
    bad clip must never take down the live pipeline processing everything
    else concurrently.
    """
    row_id = await team_radio_db.insert_pending(
        session_key=session_key,
        driver_number=capture.driver_number,
        lap_number=capture.lap_number,
        ts=capture.utc,
    )

    local_path = local_audio_path(session_key, capture)
    try:
        await team_radio_db.mark_downloading(row_id)
        url = resolve_audio_url(capture.path)
        await download_binary(url, local_path, headers=auth_headers)
        await team_radio_db.mark_downloaded(row_id, web_relative_audio_path(session_key, capture))
        logger.info("Downloaded team radio clip id=%s path=%s", row_id, local_path)
        if on_downloaded is not None:
            await on_downloaded("RADIO_CLIP_READY", row_id)
    except Exception as exc:
        logger.warning("Failed to download team radio clip id=%s: %s", row_id, exc)
        await team_radio_db.mark_failed_download(row_id, str(exc))
        return

    try:
        await team_radio_db.mark_transcribing(row_id)
        transcript = await whisper_transcriber.transcribe(local_path)
        await team_radio_db.mark_done(row_id, transcript)
        logger.info("Transcribed team radio clip id=%s", row_id)
        if on_transcribed is not None:
            await on_transcribed("RADIO_TRANSCRIPT_READY", row_id)
    except Exception as exc:
        logger.warning("Failed to transcribe team radio clip id=%s: %s", row_id, exc)
        await team_radio_db.mark_failed_transcription(row_id, str(exc))
