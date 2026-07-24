"""
Replay a captured `stream_logs/*.jsonl` file through the exact same pipeline
live messages use (LiveSessionPipeline), at a configurable speed factor.
This is the primary way to develop against and demo the whole system without
a live F1TV connection - and, since Milestone 4's reducer was already proven
error-free against the full real Qatar race log, this is what actually
exercises that pipeline end to end.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Tuple

from utils.live_session_pipeline import LiveSessionPipeline, register_pipeline, unregister_pipeline

logger = logging.getLogger(__name__)

DEFAULT_SPEED_FACTOR: float = 20.0
DEFAULT_MAX_GAP_SECONDS: float = 2.0


def iter_log_messages(log_path: Path) -> Iterator[Tuple[str, str, Any]]:
    """Yield (timestamp_iso, event_name, payload) for every "message" entry in a captured log, in file order."""
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line in %s", log_path)
                continue

            if entry.get("event_type") != "message":
                continue
            data = entry.get("data") or {}
            event_name = data.get("event_name")
            payload = data.get("payload")
            if not event_name or payload is None:
                continue
            yield entry.get("timestamp", ""), event_name, payload


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def replay_log_file(
    log_path: Path,
    pipeline: LiveSessionPipeline,
    speed_factor: float = DEFAULT_SPEED_FACTOR,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
) -> int:
    """
    Feed every message in `log_path` through `pipeline.process_message`, in
    order, pacing playback using the real gaps between each message's
    captured timestamp (scaled by `speed_factor`) rather than a flat
    per-message delay - bursts and quiet periods replay proportionally.
    Gaps are capped at `max_gap_seconds` (pre-scaling) so a stream
    reconnect/session gap in the source log doesn't stall replay for real
    time.

    Returns the number of messages replayed.
    """
    previous_ts: Optional[datetime] = None
    message_count = 0

    for timestamp_str, event_name, payload in iter_log_messages(log_path):
        current_ts = _parse_timestamp(timestamp_str)
        if previous_ts is not None and current_ts is not None:
            gap_seconds = min((current_ts - previous_ts).total_seconds(), max_gap_seconds)
            if gap_seconds > 0:
                await asyncio.sleep(gap_seconds / speed_factor)
        if current_ts is not None:
            previous_ts = current_ts

        await pipeline.process_message(event_name, payload)
        message_count += 1

    logger.info("Replay finished: %s (%d messages, speed_factor=%.1f)", log_path, message_count, speed_factor)
    return message_count


def start_replay(log_path: Path, speed_factor: float = DEFAULT_SPEED_FACTOR) -> str:
    """
    Start replaying `log_path` in the background against a fresh,
    registered LiveSessionPipeline. Returns the new session's stream_id
    immediately - the replay itself runs as a detached asyncio task.

    Mirrors utils/live_stream.py's start_stream() for the live path: same
    "start now, return an id, work happens in the background" shape.
    """
    if not log_path.exists():
        raise FileNotFoundError(f"Replay log file not found: {log_path}")

    stream_id = f"simulation_{int(datetime.now().timestamp())}"
    pipeline = LiveSessionPipeline(stream_id=stream_id, archive_path=None)  # replaying an existing archive - don't write a new one
    register_pipeline(pipeline)

    async def _run() -> None:
        try:
            await replay_log_file(log_path, pipeline, speed_factor=speed_factor)
        except Exception:
            logger.exception("Replay of %s failed", log_path)
        finally:
            unregister_pipeline(stream_id)

    asyncio.ensure_future(_run())
    return stream_id
