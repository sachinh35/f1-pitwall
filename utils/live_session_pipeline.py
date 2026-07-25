"""
Shared message-processing pipeline used identically by both the live SignalR
stream and replay/simulation mode, so the two behave identically and there is
exactly one place implementing the write path:

    archive append (unconditional, first)
        -> decode + merge into SessionState
            -> SSE broadcast (critical path - nothing gates this)
                -> lap-boundary Postgres persist (detached background task)
                -> team-radio download/transcribe (detached background task)

See the product investigation artifact's "write path" section for the full
rationale on why each step is ordered/synchronous or detached this way.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional, Set, Tuple

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from openf1_pydantic_models.f1_drivers import DriverInfo
from utils.live_persistence import (
    persist_completed_lap,
    persist_confirmed_driver_roster,
    persist_driver_roster,
    persist_race_control_entry,
    persist_session_metadata,
    persist_weather_snapshot,
)
from utils.session_metadata import fetch_driver_roster, fetch_session_metadata
from utils.session_state import CompletedLap, RadioCapture, SessionState, StateDiff
from utils.team_radio_pipeline import process_radio_capture

logger = logging.getLogger(__name__)

# Topics whose diffs carry per-driver fields under a top-level "Lines"-shaped
# dict in SessionState - the wire payload for these is simply "whatever
# changed, already resolved" rather than the raw diff, so clients never need
# to re-implement the merge logic themselves.
_PER_DRIVER_WIRE_KEYS: Dict[str, str] = {
    "TimingData": "drivers",
    "DriverList": "driver_list",
    "TimingAppData": "timing_app_data",
    "TimingStats": "timing_stats",
    "TopThree": "top_three",
}

_SESSION_WIDE_WIRE_KEYS: Dict[str, str] = {
    "TrackStatus": "track_status",
    "WeatherData": "weather",
    "SessionInfo": "session_info",
    "SessionData": "session_data",
    "SessionStatus": "session_status",
    "LapCount": "lap_count",
    "ExtrapolatedClock": "extrapolated_clock",
    "RaceControlMessages": "race_control_messages",
}


def _completed_lap_to_wire(lap: CompletedLap) -> Dict[str, Any]:
    return {
        "driver_number": lap.driver_number,
        "lap_number": lap.lap_number,
        "lap_duration_seconds": lap.lap_duration_seconds,
        "avg_speed_kmh": lap.aggregates.avg_speed_kmh,
        "max_speed_kmh": lap.aggregates.max_speed_kmh,
        "avg_throttle_pct": lap.aggregates.avg_throttle_pct,
        "drs_active_pct": lap.aggregates.drs_active_pct,
    }


def _radio_capture_to_wire(capture: RadioCapture) -> Dict[str, Any]:
    return {
        "driver_number": capture.driver_number,
        "lap_number": capture.lap_number,
        "utc": capture.utc.isoformat(),
    }


def _driver_info_to_wire(driver: DriverInfo) -> Dict[str, Any]:
    return {
        "driver_number": driver.driver_number,
        "broadcast_name": driver.broadcast_name,
        "full_name": driver.full_name,
        "name_acronym": driver.name_acronym,
        "team_name": driver.team_name,
        "team_colour": driver.team_colour,
        "first_name": driver.first_name,
        "last_name": driver.last_name,
        "headshot_url": driver.headshot_url,
        "country_code": driver.country_code,
    }


def _confirmed_entry_to_wire(entry: ConfirmedRosterEntry) -> Dict[str, Any]:
    """Same wire shape as _driver_info_to_wire, minus the OpenF1-only fields a manually-confirmed
    entry never has (broadcast_name, first/last name, headshot, country) - left None."""
    return {
        "driver_number": entry.driver_number,
        "broadcast_name": None,
        "full_name": entry.full_name,
        "name_acronym": entry.tla,
        "team_name": entry.team_name,
        "team_colour": entry.team_colour,
        "first_name": None,
        "last_name": None,
        "headshot_url": None,
        "country_code": None,
    }


def diff_to_wire(diff: StateDiff, state: SessionState) -> Dict[str, Any]:
    """
    Convert an internal StateDiff into the JSON payload sent over SSE: the
    *resolved* current state for whatever changed, not the raw diff.
    """
    wire: Dict[str, Any] = {}

    per_driver_key = _PER_DRIVER_WIRE_KEYS.get(diff.event_name)
    if per_driver_key is not None:
        source: Dict[int, Dict[str, Any]] = getattr(state, per_driver_key)
        wire[per_driver_key] = {str(d): source.get(d, {}) for d in set(diff.changed_driver_numbers)}

    session_wide_key = _SESSION_WIDE_WIRE_KEYS.get(diff.event_name)
    if session_wide_key is not None:
        wire[session_wide_key] = getattr(state, session_wide_key)

    if diff.event_name == "CarData.z":
        wire["telemetry"] = {
            str(d): sample
            for d in set(diff.changed_driver_numbers)
            if (sample := state.latest_telemetry_sample(d)) is not None
        }
    elif diff.event_name == "Position.z":
        wire["positions"] = {
            str(d): sample
            for d in set(diff.changed_driver_numbers)
            if (sample := state.latest_position_sample(d)) is not None
        }

    if diff.completed_laps:
        wire["completed_laps"] = [_completed_lap_to_wire(lap) for lap in diff.completed_laps]
    if diff.new_radio_captures:
        wire["new_radio_captures"] = [_radio_capture_to_wire(c) for c in diff.new_radio_captures]

    return wire


class LiveSessionPipeline:
    """
    One instance per live or simulated session. Owns the SessionState
    reducer, the raw-archive file, and the set of connected SSE subscribers
    for this stream_id.
    """

    def __init__(
        self,
        stream_id: str,
        archive_path: Optional[Path] = None,
        confirmed_roster: Optional[List[ConfirmedRosterEntry]] = None,
    ) -> None:
        self.stream_id = stream_id
        self.state = SessionState()
        self._subscribers: Dict[int, "asyncio.Queue[Dict[str, Any]]"] = {}
        self._next_subscriber_id: int = 0
        self._next_event_id: int = 0
        self._archive_file = open(archive_path, "a", encoding="utf-8") if archive_path else None
        self._background_tasks: Set[asyncio.Task] = set()
        self._messages_since_flush: int = 0
        self._session_meta_fetch_started: bool = False

        # A user-confirmed pre-race lineup, if the caller supplied one, is known
        # immediately - no need to wait on SessionInfo/an OpenF1 fetch for the
        # roster itself (only for session metadata, which still comes from
        # OpenF1). See ConfirmedRosterEntry for why this exists.
        self._confirmed_roster: Optional[List[ConfirmedRosterEntry]] = confirmed_roster
        if confirmed_roster is not None:
            self.state.set_driver_roster(
                {entry.driver_number: _confirmed_entry_to_wire(entry) for entry in confirmed_roster}
            )

    def subscribe(self) -> Tuple[int, "asyncio.Queue[Dict[str, Any]]"]:
        """Register a new SSE client. Caller must call unsubscribe() when the connection closes."""
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        queue.put_nowait(self._make_message("snapshot", self.state.snapshot()))
        self._subscribers[subscriber_id] = queue
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: int) -> None:
        self._subscribers.pop(subscriber_id, None)

    def _make_message(self, event_name: str, data: Any) -> Dict[str, Any]:
        self._next_event_id += 1
        return {"id": self._next_event_id, "event": event_name, "data": data}

    async def _broadcast(self, event_name: str, data: Any) -> None:
        message = self._make_message(event_name, data)
        for queue in list(self._subscribers.values()):
            queue.put_nowait(message)

    def log_event(self, event_type: str, data: Any) -> None:
        """
        Archive a non-"message" stream event (connection/subscription/stream
        status/error) to the same raw log `process_message` writes to -
        matches the existing captured-log format. Low-frequency, so flushed
        immediately rather than batched.
        """
        if self._archive_file is None:
            return
        entry = {
            "timestamp": datetime.now().isoformat(),
            "stream_id": self.stream_id,
            "event_type": event_type,
            "data": data,
        }
        self._archive_file.write(json.dumps(entry, default=str) + "\n")
        self._archive_file.flush()

    def _archive_raw(self, event_name: str, payload: Any) -> None:
        """Append the raw message to the cold-tier archive - unconditional, and first, before decoding.

        Not flushed per message (that would put disk I/O on the hot path for
        no real durability benefit at this message rate); flushed every 50
        messages instead, plus unconditionally on close()."""
        if self._archive_file is None:
            return
        entry = {
            "timestamp": datetime.now().isoformat(),
            "stream_id": self.stream_id,
            "event_type": "message",
            "data": {"event_name": event_name, "payload": payload},
        }
        self._archive_file.write(json.dumps(entry, default=str) + "\n")
        self._messages_since_flush += 1
        if self._messages_since_flush >= 50:
            self._archive_file.flush()
            self._messages_since_flush = 0

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Schedule a detached background task, keeping a reference so it isn't garbage-collected mid-flight
        (asyncio only holds a weak reference to a task otherwise)."""
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def process_message(self, event_name: str, payload: Any) -> None:
        """
        The write path for one incoming message (live or replayed): archive
        first, decode+merge, broadcast immediately, then detached background
        work for anything that just settled. A failure decoding/merging one
        message is logged and skipped - it must never take down the pipeline
        processing everything else.
        """
        self._archive_raw(event_name, payload)

        try:
            diff = self.state.apply(event_name, payload)
        except Exception:
            logger.exception("Failed to apply event_name=%s to session state, skipping", event_name)
            return

        await self._broadcast(event_name, diff_to_wire(diff, self.state))

        if event_name == "SessionInfo" and not self._session_meta_fetch_started and self.state.session_key is not None:
            self._session_meta_fetch_started = True
            self._spawn(self._fetch_and_broadcast_session_meta())

        for completed_lap in diff.completed_laps:
            self._spawn(self._persist_completed_lap(completed_lap))

        for capture in diff.new_radio_captures:
            if self.state.session_key is not None:
                self._spawn(
                    process_radio_capture(
                        session_key=self.state.session_key,
                        capture=capture,
                        on_downloaded=self._broadcast_radio_event,
                        on_transcribed=self._broadcast_radio_event,
                    )
                )

        if diff.new_weather_snapshot is not None and self.state.session_key is not None:
            self._spawn(self._persist_weather(diff.new_weather_snapshot))

        for entry in diff.new_race_control_entries:
            self._spawn(self._persist_race_control_entry(entry))

    async def _persist_completed_lap(self, lap: CompletedLap) -> None:
        if self.state.session_key is None or self.state.meeting_key is None:
            logger.warning(
                "Dropping completed-lap persist for driver=%s lap=%s - session_key/meeting_key not yet known",
                lap.driver_number, lap.lap_number,
            )
            return
        try:
            await persist_completed_lap(self.state.session_key, self.state.meeting_key, lap)
        except Exception:
            logger.exception(
                "Failed to persist completed lap driver=%s lap=%s", lap.driver_number, lap.lap_number
            )

    async def _fetch_and_broadcast_session_meta(self) -> None:
        """One-shot, triggered the first time SessionInfo reveals this session's key: fetch its
        circuit/location/date/type from OpenF1 and persist it.

        The driver roster is handled differently depending on whether the caller supplied a
        confirmed_roster upfront: if so, it's already set on self.state (from __init__, before any
        subscriber could have connected) and just needs persisting now that session_key is known - the
        OpenF1 roster fetch is skipped entirely, since it can't be trusted for a genuinely live session
        anyway (see ConfirmedRosterEntry). Otherwise, fall back to the OpenF1-backed fetch/broadcast
        this always did (correct for replays of already-historical sessions - see session_metadata.py).
        """
        session_key = self.state.session_key
        if session_key is None:
            return

        if self._confirmed_roster is not None:
            session_meta = await fetch_session_metadata(session_key)
            if session_meta is not None:
                try:
                    await persist_session_metadata(session_meta)
                except Exception:
                    logger.exception("Failed to persist session metadata for session_key=%s", session_key)
            try:
                await persist_confirmed_driver_roster(session_key, self._confirmed_roster)
            except Exception:
                logger.exception("Failed to persist confirmed driver roster for session_key=%s", session_key)
            return

        session_meta, drivers = await asyncio.gather(
            fetch_session_metadata(session_key), fetch_driver_roster(session_key)
        )

        if session_meta is not None:
            try:
                await persist_session_metadata(session_meta)
            except Exception:
                logger.exception("Failed to persist session metadata for session_key=%s", session_key)

        if not drivers:
            logger.warning("OpenF1 returned no driver roster for session_key=%s", session_key)
            return

        try:
            await persist_driver_roster(session_key, drivers)
        except Exception:
            logger.exception("Failed to persist driver roster for session_key=%s", session_key)

        roster_by_number = {driver.driver_number: _driver_info_to_wire(driver) for driver in drivers}
        self.state.set_driver_roster(roster_by_number)
        await self._broadcast(
            "driver_roster", {"driver_roster": {str(k): v for k, v in roster_by_number.items()}}
        )

    async def _broadcast_radio_event(self, event_name: str, row_id: int) -> None:
        """Forward team_radio_pipeline's on_downloaded/on_transcribed callbacks onto this session's SSE
        broadcast, so the frontend learns a clip is playable (RADIO_CLIP_READY) and, a few seconds later,
        that its transcript is ready (RADIO_TRANSCRIPT_READY) - without polling."""
        await self._broadcast(event_name, {"row_id": row_id})

    async def _persist_weather(self, weather: Dict[str, Any]) -> None:
        try:
            await persist_weather_snapshot(self.state.session_key, weather)
        except Exception:
            logger.exception("Failed to persist weather snapshot for session_key=%s", self.state.session_key)

    async def _persist_race_control_entry(self, entry: Dict[str, Any]) -> None:
        if self.state.session_key is None:
            logger.warning("Dropping race control persist - session_key not yet known")
            return
        try:
            await persist_race_control_entry(self.state.session_key, self.state.meeting_key, entry)
        except Exception:
            logger.exception("Failed to persist race control entry for session_key=%s", self.state.session_key)

    def close(self) -> None:
        if self._archive_file is not None:
            self._archive_file.close()
            self._archive_file = None


# Registry of active pipelines by stream_id - the one place both a live
# SignalR stream and a replay/simulation session get looked up from, so
# main.py's SSE endpoint doesn't need to know which kind of session it is.
_active_pipelines: Dict[str, LiveSessionPipeline] = {}


def register_pipeline(pipeline: LiveSessionPipeline) -> None:
    _active_pipelines[pipeline.stream_id] = pipeline


def get_pipeline(stream_id: str) -> Optional[LiveSessionPipeline]:
    return _active_pipelines.get(stream_id)


def unregister_pipeline(stream_id: str) -> None:
    pipeline = _active_pipelines.pop(stream_id, None)
    if pipeline is not None:
        pipeline.close()
