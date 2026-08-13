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

from utils import radio_analysis, team_radio_db, whisper_transcriber
from utils.http_client import download_binary
from utils.session_state import RadioCapture

logger = logging.getLogger(__name__)

# Confirmed by a real successful fetch (200, valid MPEG audio) against a captured
# historical session - see below, this host needs no authentication at all for
# static content. The catch (also empirically confirmed - a bare `{base}/{path}`
# URL 403s with a raw S3/CloudFront AccessDenied) is that the real URL must be
# rooted under the session's own directory, not `/static/` directly.
F1_STATIC_CONTENT_BASE_URL: str = "https://livetiming.formula1.com/static"

AUDIO_CACHE_DIR: Path = Path("audio_cache")

# Invoked after the clip is downloaded (playable) and again once it's
# transcribed (caption ready). Owned by whoever wires up the SSE broadcast
# (Milestone 6) - this module doesn't need to know SSE exists.
BroadcastCallback = Callable[[str, int], Awaitable[None]]


def resolve_audio_url(relative_path: str, session_path: Optional[str] = None) -> str:
    """
    Resolve a TeamRadio message's relative `Path` (e.g. "TeamRadio/x.mp3") into a
    fetchable URL. `session_path` is F1's own SessionInfo.Path field (e.g.
    "2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/") - required in practice:
    every static asset for a session lives under that session-specific directory,
    not directly under /static/. A bare `{base}/{relative_path}` (no session_path)
    404/403s - confirmed directly against F1's real CDN, not assumed - so
    session_path is only optional here for callers that haven't seen SessionInfo
    yet (the capture is archived either way; download will simply fail until a
    later capture arrives with session_path available).
    """
    if session_path:
        return f"{F1_STATIC_CONTENT_BASE_URL}/{session_path.strip('/')}/{relative_path}"
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
    session_path: Optional[str] = None,
    on_downloaded: Optional[BroadcastCallback] = None,
    on_transcribed: Optional[BroadcastCallback] = None,
    on_analyzed: Optional[BroadcastCallback] = None,
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
        capture_path=capture.path,
        qualifying_part=capture.qualifying_part,
    )
    if row_id is None:
        # Already have a row for this exact capture (session_key, capture_path) - it was
        # already downloaded/transcribed/analyzed by a previous run. SessionState._seen_radio_paths
        # only dedupes within one process's lifetime, so this is the durable check that actually
        # prevents re-running Whisper/Gemini on every re-simulation or backend restart.
        logger.debug(
            "Skipping already-processed team radio capture session_key=%s path=%s", session_key, capture.path
        )
        return

    local_path = local_audio_path(session_key, capture)
    try:
        await team_radio_db.mark_downloading(row_id)
        url = resolve_audio_url(capture.path, session_path=session_path)
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
        return

    # Best-effort: the transcript itself is already saved and marked done above regardless
    # of what happens here, so a Gemini failure (quota, network, bad model id) never
    # regresses an otherwise-successful transcription.
    try:
        analysis = await radio_analysis.analyze_transcript(
            driver_label=f"Driver #{capture.driver_number}", lap_number=capture.lap_number, transcript=transcript
        )
        await team_radio_db.mark_analyzed(row_id, analysis.speaker_role, analysis.is_notable, analysis.notable_reason)
        logger.info(
            "Analyzed team radio clip id=%s speaker_role=%s is_notable=%s",
            row_id, analysis.speaker_role, analysis.is_notable,
        )
        if on_analyzed is not None:
            await on_analyzed("RADIO_ANALYSIS_READY", row_id)
    except Exception as exc:
        logger.warning("Failed to analyze team radio clip id=%s: %s", row_id, exc)
