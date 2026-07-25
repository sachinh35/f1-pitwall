"""
Stateful reducer for F1 live-timing sessions.

F1's SignalR feed sends a full snapshot once per topic on subscribe, then
partial diffs after - most fields are only ever present in whichever message
last changed them (confirmed directly against captured logs; see e.g. a real
`TimingData` message containing nothing but
`{"Lines": {"12": {"Sectors": {"1": {"Segments": {"0": {"Status": 2048}}}}}}}`).
This module turns that diff stream into one coherent "current state of the
session" (the Hot tier), and detects the exact moment a lap completes so its
buffered telemetry/position samples can be flushed to Postgres (the Warm tier).

Field names used below (NumberOfLaps, GapToLeader, IntervalToPositionAhead,
Position, LastLapTime, etc.) were confirmed by enumerating every key that
actually appears in TimingData.Lines across a full captured race, not assumed
from documentation - F1 publishes none for this feed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from utils.telemetry_decoder import (
    DRS_ACTIVE_CODES,
    CarDataFrame,
    PositionFrame,
    decode_car_data,
    decode_position,
)

logger = logging.getLogger(__name__)


def deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `update` into `base` in place, returning `base`.

    Matches F1's live-timing diff semantics: nested dicts are merged key by
    key; any non-dict value (including lists and scalars) simply replaces
    whatever was there before at that key. This one function is deliberately
    reused for every per-topic merge below (TimingData, TimingAppData,
    TopThree, DriverList, TrackStatus, WeatherData, ...) instead of writing
    bespoke merge logic per topic.
    """
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _parse_utc(value: str) -> datetime:
    """Parse F1's UTC timestamp strings (trailing 'Z', variable fractional-second precision)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class LapAggregates:
    """Derived stats computed once, at lap completion - never recomputed from raw arrays on read."""
    avg_speed_kmh: Optional[int]
    max_speed_kmh: Optional[int]
    avg_throttle_pct: Optional[int]
    drs_active_pct: Optional[int]


@dataclass
class TelemetrySampleBuffer:
    """Accumulates one driver's telemetry/position samples for the lap currently in progress."""
    dt_ms: List[int] = field(default_factory=list)
    speed: List[int] = field(default_factory=list)
    rpm: List[int] = field(default_factory=list)
    gear: List[int] = field(default_factory=list)
    throttle_pct: List[int] = field(default_factory=list)
    brake_pct: List[int] = field(default_factory=list)
    drs: List[int] = field(default_factory=list)
    position_dt_ms: List[int] = field(default_factory=list)
    x: List[int] = field(default_factory=list)
    y: List[int] = field(default_factory=list)
    z: List[int] = field(default_factory=list)
    position_status: List[str] = field(default_factory=list)
    _telemetry_start_utc: Optional[datetime] = None
    _position_start_utc: Optional[datetime] = None

    def add_car_sample(
        self,
        utc: datetime,
        rpm: int,
        speed_kmh: int,
        gear: int,
        throttle_pct: int,
        brake_pct: int,
        drs: int,
    ) -> None:
        self._telemetry_start_utc = self._telemetry_start_utc or utc
        self.dt_ms.append(_millis_since(self._telemetry_start_utc, utc))
        self.rpm.append(rpm)
        self.speed.append(speed_kmh)
        self.gear.append(gear)
        self.throttle_pct.append(throttle_pct)
        self.brake_pct.append(brake_pct)
        self.drs.append(drs)

    def add_position_sample(self, utc: datetime, x: int, y: int, z: int, status: str) -> None:
        self._position_start_utc = self._position_start_utc or utc
        self.position_dt_ms.append(_millis_since(self._position_start_utc, utc))
        self.x.append(x)
        self.y.append(y)
        self.z.append(z)
        self.position_status.append(status)

    def compute_aggregates(self, drs_active_codes: frozenset[int]) -> LapAggregates:
        sample_count = len(self.speed)
        if sample_count == 0:
            return LapAggregates(None, None, None, None)
        active_count = sum(1 for d in self.drs if d in drs_active_codes)
        return LapAggregates(
            avg_speed_kmh=round(sum(self.speed) / sample_count),
            max_speed_kmh=max(self.speed),
            avg_throttle_pct=round(sum(self.throttle_pct) / sample_count),
            drs_active_pct=round(100 * active_count / sample_count),
        )


def _millis_since(start: datetime, current: datetime) -> int:
    return int((current - start).total_seconds() * 1000)


@dataclass
class CompletedLap:
    """Everything needed to persist one driver's just-finished lap to Postgres."""
    driver_number: int
    lap_number: int
    lap_duration_seconds: Optional[float]
    aggregates: LapAggregates
    telemetry: TelemetrySampleBuffer


def parse_lap_time_to_seconds(value: Optional[str]) -> Optional[float]:
    """
    Parse F1's lap-time strings ("1:27.150" or, rarely, just "27.150") into seconds.
    Returns None for missing/unparseable input rather than raising, since a
    malformed lap time shouldn't take down the reducer mid-race.
    """
    if not value:
        return None
    try:
        parts = value.split(":")
        if len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        return float(parts[0])
    except (ValueError, IndexError):
        logger.warning("Could not parse lap time value=%r", value)
        return None


@dataclass
class RadioCapture:
    """A newly-seen TeamRadio clip, enriched with the driver's current lap (not present in the raw message)."""
    driver_number: int
    utc: datetime
    path: str
    lap_number: Optional[int]


@dataclass
class StateDiff:
    """What changed as a result of one `SessionState.apply()` call."""
    event_name: str
    changed_driver_numbers: List[int] = field(default_factory=list)
    completed_laps: List[CompletedLap] = field(default_factory=list)
    new_radio_captures: List[RadioCapture] = field(default_factory=list)
    # WeatherData/RaceControlMessages are already-complete facts the instant
    # they arrive (see the "diff, not snapshot" distinction elsewhere in this
    # module) - unlike TimingData etc., they're settled enough to persist to
    # the Warm tier immediately, not just on a lap boundary.
    new_weather_snapshot: Optional[Dict[str, Any]] = None
    new_race_control_entries: List[Dict[str, Any]] = field(default_factory=list)


class SessionState:
    """
    One instance per live or simulated session. Owns the full current
    picture of the race (the Hot tier), built by merging every diff the
    SignalR feed sends, and buffers each driver's in-progress lap so its
    aggregates/telemetry/position can be handed off the moment the lap ends.
    """

    def __init__(self, session_key: Optional[int] = None) -> None:
        self.session_key: Optional[int] = session_key
        self.meeting_key: Optional[int] = None

        # driver_number -> merged fields, one dict per topic.
        self.drivers: Dict[int, Dict[str, Any]] = {}
        self.driver_list: Dict[int, Dict[str, Any]] = {}
        self.timing_app_data: Dict[int, Dict[str, Any]] = {}
        self.timing_stats: Dict[int, Dict[str, Any]] = {}
        self.top_three: Dict[int, Dict[str, Any]] = {}

        # Session-wide, replace-style state.
        self.track_status: Dict[str, Any] = {}
        self.weather: Dict[str, Any] = {}
        self.session_info: Dict[str, Any] = {}
        self.session_data: Dict[str, Any] = {}
        self.session_status: Dict[str, Any] = {}
        self.lap_count: Dict[str, Any] = {}
        self.extrapolated_clock: Dict[str, Any] = {}

        # Append-only.
        self.race_control_messages: Dict[str, Any] = {}

        # Set once per session, out-of-band from an OpenF1 fetch triggered
        # when SessionInfo reveals this session's key - never comes from a
        # SignalR message itself (DriverList only ever carries a grid "Line"
        # number, no names/teams), so it isn't wired through the handler
        # dispatch below.
        self.driver_roster: Dict[int, Dict[str, Any]] = {}

        self._seen_radio_paths: Set[str] = set()
        self._current_lap_by_driver: Dict[int, int] = {}
        self._telemetry_buffers: Dict[int, TelemetrySampleBuffer] = {}

        self._handlers: Dict[str, Callable[[Any], StateDiff]] = {
            "TimingData": self._apply_timing_data,
            "CarData.z": self._apply_car_data,
            "Position.z": self._apply_position,
            "DriverList": self._apply_driver_list,
            "TimingAppData": lambda payload: self._apply_lines_topic(payload, self.timing_app_data, "TimingAppData"),
            "TimingStats": lambda payload: self._apply_lines_topic(payload, self.timing_stats, "TimingStats"),
            "TopThree": lambda payload: self._apply_lines_topic(payload, self.top_three, "TopThree"),
            "TrackStatus": lambda payload: self._apply_replace(payload, self.track_status, "TrackStatus"),
            "WeatherData": self._apply_weather_data,
            "SessionInfo": self._apply_session_info,
            "SessionData": lambda payload: self._apply_replace(payload, self.session_data, "SessionData"),
            "SessionStatus": lambda payload: self._apply_replace(payload, self.session_status, "SessionStatus"),
            "LapCount": lambda payload: self._apply_replace(payload, self.lap_count, "LapCount"),
            "ExtrapolatedClock": lambda payload: self._apply_replace(payload, self.extrapolated_clock, "ExtrapolatedClock"),
            "RaceControlMessages": self._apply_race_control,
            "TeamRadio": self._apply_team_radio,
        }

    def apply(self, event_name: str, payload: Any) -> StateDiff:
        """Merge one decoded SignalR message into state, returning what changed."""
        handler = self._handlers.get(event_name)
        if handler is None:
            logger.debug("No handler for event_name=%s, ignoring", event_name)
            return StateDiff(event_name=event_name)
        return handler(payload)

    def set_driver_roster(self, drivers: Dict[int, Dict[str, Any]]) -> None:
        """Set once per session from an out-of-band OpenF1 fetch - see the comment on
        self.driver_roster in __init__ for why this bypasses apply()/the handler dispatch."""
        self.driver_roster = drivers

    def current_lap_for(self, driver_number: int) -> Optional[int]:
        """The driver's current lap number, or None if not yet known."""
        return self._current_lap_by_driver.get(driver_number)

    def latest_telemetry_sample(self, driver_number: int) -> Optional[Dict[str, Any]]:
        """The most recent CarData.z sample buffered for this driver's in-progress lap, or None if none yet."""
        buffer = self._telemetry_buffers.get(driver_number)
        if buffer is None or not buffer.speed:
            return None
        return {
            "speed_kmh": buffer.speed[-1],
            "rpm": buffer.rpm[-1],
            "gear": buffer.gear[-1],
            "throttle_pct": buffer.throttle_pct[-1],
            "brake_pct": buffer.brake_pct[-1],
            "drs": buffer.drs[-1],
        }

    def latest_position_sample(self, driver_number: int) -> Optional[Dict[str, Any]]:
        """The most recent Position.z sample buffered for this driver's in-progress lap, or None if none yet."""
        buffer = self._telemetry_buffers.get(driver_number)
        if buffer is None or not buffer.x:
            return None
        return {"x": buffer.x[-1], "y": buffer.y[-1], "z": buffer.z[-1], "status": buffer.position_status[-1]}

    def snapshot(self) -> Dict[str, Any]:
        """Full current state - sent to a newly-connected SSE client, or periodically
        serialized for crash recovery."""
        return {
            "session_key": self.session_key,
            "drivers": self.drivers,
            "driver_list": self.driver_list,
            "timing_app_data": self.timing_app_data,
            "timing_stats": self.timing_stats,
            "top_three": self.top_three,
            "track_status": self.track_status,
            "weather": self.weather,
            "session_info": self.session_info,
            "session_data": self.session_data,
            "session_status": self.session_status,
            "lap_count": self.lap_count,
            "extrapolated_clock": self.extrapolated_clock,
            "race_control_messages": self.race_control_messages,
            "driver_roster": self.driver_roster,
        }

    # ---- per-topic handlers ----

    def _buffer_for(self, driver_number: int) -> TelemetrySampleBuffer:
        return self._telemetry_buffers.setdefault(driver_number, TelemetrySampleBuffer())

    def _apply_timing_data(self, payload: Dict[str, Any]) -> StateDiff:
        diff = StateDiff(event_name="TimingData")
        for driver_str, fields in payload.get("Lines", {}).items():
            driver_number = int(driver_str)
            deep_merge(self.drivers.setdefault(driver_number, {}), fields)
            diff.changed_driver_numbers.append(driver_number)

            if "NumberOfLaps" in fields:
                completed = self._advance_lap(driver_number, fields["NumberOfLaps"])
                if completed is not None:
                    diff.completed_laps.append(completed)
        return diff

    def _advance_lap(self, driver_number: int, new_lap_number: int) -> Optional[CompletedLap]:
        """
        Detect a lap boundary: whenever a driver's NumberOfLaps increases, the
        *previous* lap just completed. Flushes and resets that driver's
        telemetry buffer. Returns None if this isn't actually an advance
        (first sighting of the driver, or a duplicate/out-of-order message).
        """
        previous_lap = self._current_lap_by_driver.get(driver_number)
        self._current_lap_by_driver[driver_number] = new_lap_number

        if previous_lap is None or new_lap_number <= previous_lap:
            return None

        # The message that announces the NEW lap number carries the just-completed
        # lap's time in the same payload (confirmed against real captured data:
        # the message with NumberOfLaps=2 is the one carrying LastLapTime for lap 1).
        # `self.drivers` was already merged with this message's fields by the caller.
        last_lap_time = self.drivers.get(driver_number, {}).get("LastLapTime", {})
        lap_duration_seconds = parse_lap_time_to_seconds(last_lap_time.get("Value"))

        buffer = self._telemetry_buffers.pop(driver_number, None)
        self._telemetry_buffers[driver_number] = TelemetrySampleBuffer()
        if buffer is None or not buffer.speed:
            return None

        return CompletedLap(
            driver_number=driver_number,
            lap_number=previous_lap,
            lap_duration_seconds=lap_duration_seconds,
            aggregates=buffer.compute_aggregates(DRS_ACTIVE_CODES),
            telemetry=buffer,
        )

    def _apply_car_data(self, payload: str) -> StateDiff:
        diff = StateDiff(event_name="CarData.z")
        frame: CarDataFrame = decode_car_data(payload)
        for sample in frame.samples:
            for driver_number, channels in sample.cars.items():
                self._buffer_for(driver_number).add_car_sample(
                    utc=sample.utc,
                    rpm=channels.rpm,
                    speed_kmh=channels.speed_kmh,
                    gear=channels.gear,
                    throttle_pct=channels.throttle_pct,
                    brake_pct=channels.brake_pct,
                    drs=channels.drs,
                )
                diff.changed_driver_numbers.append(driver_number)
        return diff

    def _apply_position(self, payload: str) -> StateDiff:
        diff = StateDiff(event_name="Position.z")
        frame: PositionFrame = decode_position(payload)
        for sample in frame.samples:
            for driver_number, entry in sample.cars.items():
                self._buffer_for(driver_number).add_position_sample(
                    utc=sample.utc, x=entry.x, y=entry.y, z=entry.z, status=entry.status,
                )
                diff.changed_driver_numbers.append(driver_number)
        return diff

    def _apply_driver_list(self, payload: Dict[str, Any]) -> StateDiff:
        diff = StateDiff(event_name="DriverList")
        for driver_str, fields in payload.items():
            if driver_str.startswith("_") or not isinstance(fields, dict):
                continue
            driver_number = int(driver_str)
            deep_merge(self.driver_list.setdefault(driver_number, {}), fields)
            diff.changed_driver_numbers.append(driver_number)
        return diff

    def _apply_lines_topic(
        self, payload: Dict[str, Any], target: Dict[int, Dict[str, Any]], event_name: str
    ) -> StateDiff:
        diff = StateDiff(event_name=event_name)
        for driver_str, fields in payload.get("Lines", {}).items():
            driver_number = int(driver_str)
            deep_merge(target.setdefault(driver_number, {}), fields)
            diff.changed_driver_numbers.append(driver_number)
        return diff

    def _apply_replace(self, payload: Dict[str, Any], target: Dict[str, Any], event_name: str) -> StateDiff:
        deep_merge(target, payload)
        return StateDiff(event_name=event_name)

    def _apply_session_info(self, payload: Dict[str, Any]) -> StateDiff:
        """
        Same replace-style merge as every other session-wide topic, plus
        capturing session_key/meeting_key - confirmed from a real SessionInfo
        payload: `{"Meeting": {"Key": 1275, ...}, "Key": 9850, ...}`, where
        the top-level "Key" is the session key and "Meeting.Key" is the
        meeting key. Everything that persists to Postgres needs both.
        """
        deep_merge(self.session_info, payload)
        if "Key" in payload:
            self.session_key = payload["Key"]
        meeting = payload.get("Meeting")
        if isinstance(meeting, dict) and "Key" in meeting:
            self.meeting_key = meeting["Key"]
        return StateDiff(event_name="SessionInfo")

    def _apply_weather_data(self, payload: Dict[str, Any]) -> StateDiff:
        """WeatherData ticks are complete facts on arrival - persisted immediately, not batched to a lap boundary."""
        deep_merge(self.weather, payload)
        return StateDiff(event_name="WeatherData", new_weather_snapshot=dict(self.weather))

    def _apply_race_control(self, payload: Dict[str, Any]) -> StateDiff:
        """Race control messages are complete facts on arrival (each index is unique and never revisited) -
        every entry in this payload is new and gets persisted immediately, not batched to a lap boundary.

        F1 sends this as a list (no index at all) on the very first RaceControlMessages event of a
        session, and as a dict (index -> message) on every one after that - the same list-then-dict
        quirk already handled on TeamRadio.Captures, confirmed here directly across three captured
        sessions (always exactly one list-form event, always exactly one item, always first). List
        entries get a synthetic non-positive string index (F1's own real indices always start at "1"
        and count up), so it can never collide with a real one and still sorts as the oldest entry
        wherever a caller does `Number(index)` and sorts descending (the frontend's race control feed).
        """
        raw_messages = payload.get("Messages", {})
        if isinstance(raw_messages, list):
            messages = {str(-i): message for i, message in enumerate(raw_messages)}
        else:
            messages = raw_messages

        deep_merge(self.race_control_messages, messages)
        new_entries = [{"index": index, **fields} for index, fields in messages.items()]
        return StateDiff(event_name="RaceControlMessages", new_race_control_entries=new_entries)

    def _apply_team_radio(self, payload: Dict[str, Any]) -> StateDiff:
        diff = StateDiff(event_name="TeamRadio")
        captures = payload.get("Captures", {})
        # F1 sends this as a list on the very first capture of a session and
        # as a dict (index -> capture) afterwards - both forms observed
        # directly in captured logs.
        capture_items = captures if isinstance(captures, list) else list(captures.values())

        for capture in capture_items:
            path = capture.get("Path")
            if not path or path in self._seen_radio_paths:
                continue
            self._seen_radio_paths.add(path)

            driver_number = int(capture["RacingNumber"])
            diff.new_radio_captures.append(
                RadioCapture(
                    driver_number=driver_number,
                    utc=_parse_utc(capture["Utc"]),
                    path=path,
                    lap_number=self.current_lap_for(driver_number),
                )
            )
        return diff
