"""
Feed a live-growing stream_logs/live_<session-name>.jsonl file (written by the
standalone scripts/capture_stream.py process) through a LiveSessionPipeline: first
fast-replay everything already written - catching state up to "now" - then keep
polling for and feeding new lines as the capture process appends them, indefinitely.

This is the backend's half of the capture/backend split: scripts/capture_stream.py
owns writing the raw archive and never stops; this module is what lets the backend
(re)derive full current state from that archive on demand, so restarting the backend
(a crash, a redeploy, a developer iterating on the frontend) never loses live data -
call start_tail() again and it catches straight back up. See utils/raw_capture.py and
main.py's auto-reattach logic in GET /live/{stream_id}/events.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from utils.live_session_pipeline import LiveSessionPipeline, register_pipeline, unregister_pipeline
from utils.time_utils import parse_iso_timestamp

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS: float = 0.5

# Stop events for in-flight tail tasks, by stream_id - lets stop_tail() end a tail
# gracefully (used when a session is explicitly torn down) rather than only ever via
# the pipeline being garbage-collected.
_tail_stop_events: Dict[str, asyncio.Event] = {}


def _read_new_entries(f: TextIO, offset: int) -> Tuple[List[dict], int]:
    """Read every complete (newline-terminated) JSON line from `offset` onward. A trailing
    partial line - the capture process flushing mid-write - is left for the next call
    rather than consumed, so offset never advances past an incomplete line."""
    f.seek(offset)
    entries: List[dict] = []
    while True:
        line = f.readline()
        if not line or not line.endswith("\n"):
            break
        stripped = line.strip()
        offset = f.tell()
        if not stripped:
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSON line while tailing %s", getattr(f, "name", "<file>"))
    return entries, offset


def _entry_to_message(entry: dict) -> Optional[Tuple[str, Any, Optional[datetime]]]:
    if entry.get("event_type") != "message":
        return None
    data = entry.get("data") or {}
    event_name = data.get("event_name")
    payload = data.get("payload")
    if not event_name or payload is None:
        return None
    return event_name, payload, parse_iso_timestamp(entry.get("timestamp"))


async def tail_log_file(
    log_path: Path,
    pipeline: LiveSessionPipeline,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Catch `pipeline` up on everything currently in `log_path`, then poll for and feed
    new appended lines forever (until `stop_event` is set). Runs as a detached task -
    see start_tail()."""
    offset = 0
    caught_up = 0
    with open(log_path, "r", encoding="utf-8") as f:
        entries, offset = _read_new_entries(f, offset)
        for entry in entries:
            parsed = _entry_to_message(entry)
            if parsed is None:
                continue
            event_name, payload, event_time = parsed
            await pipeline.process_message(event_name, payload, event_time=event_time)
            caught_up += 1
        logger.info("Tailing %s: caught up on %d existing messages, now following live", log_path, caught_up)

        while stop_event is None or not stop_event.is_set():
            await asyncio.sleep(poll_interval)
            entries, offset = _read_new_entries(f, offset)
            for entry in entries:
                parsed = _entry_to_message(entry)
                if parsed is None:
                    continue
                event_name, payload, event_time = parsed
                await pipeline.process_message(event_name, payload, event_time=event_time)


def _stream_id_for_log_path(log_path: Path) -> str:
    stem = log_path.stem
    return stem if stem.startswith("live_") else f"live_{stem}"


def start_tail(
    log_path: Path,
    stream_id: Optional[str] = None,
    confirmed_roster: Optional[List[ConfirmedRosterEntry]] = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> str:
    """
    Start (or resume) tailing `log_path` against a fresh, registered LiveSessionPipeline.
    Returns the stream_id immediately, the same shape as replay.start_replay()/
    live_stream.start_stream() - main.py's callers don't need to know which kind of
    session they're looking at.

    stream_id defaults to a stable name derived from the log filename
    (live_<session-name>, matching scripts/capture_stream.py's naming) rather than a
    fresh timestamp each call, so re-calling this after a backend restart reattaches
    under the exact same stream_id a frontend may already be trying to reconnect to.
    """
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    resolved_stream_id = stream_id or _stream_id_for_log_path(log_path)
    pipeline = LiveSessionPipeline(
        stream_id=resolved_stream_id, archive_path=None, confirmed_roster=confirmed_roster
    )  # tailing an archive scripts/capture_stream.py already owns writing - don't open a second writer
    register_pipeline(pipeline)

    stop_event = asyncio.Event()
    _tail_stop_events[resolved_stream_id] = stop_event

    async def _run() -> None:
        try:
            await tail_log_file(log_path, pipeline, poll_interval=poll_interval, stop_event=stop_event)
        except Exception:
            logger.exception("Tailing %s failed", log_path)
        finally:
            unregister_pipeline(resolved_stream_id)
            _tail_stop_events.pop(resolved_stream_id, None)

    asyncio.ensure_future(_run())
    return resolved_stream_id


def stop_tail(stream_id: str) -> bool:
    """Stop an in-flight tail task. Returns True if one was found and signaled."""
    stop_event = _tail_stop_events.get(stream_id)
    if stop_event is None:
        return False
    stop_event.set()
    return True
