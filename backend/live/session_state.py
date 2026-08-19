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
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from live.telemetry_decoder import (
    DRS_ACTIVE_CODES,
    CarDataFrame,
    PositionFrame,
    decode_car_data,
    decode_position,
)

logger = logging.getLogger(__name__)

# Battle Radar thresholds: a driver only ever shows an alert while *closing*
# on the car ahead (never merely running a small/medium gap) - see
# _update_battle_radar. "battle" is the more urgent tier (an overtake attempt
# is plausible within a lap or two); "upcoming" is the earlier warning.
BATTLE_GAP_THRESHOLD_SECONDS = 1.3
UPCOMING_GAP_THRESHOLD_SECONDS = 2.0

# Matches both observed RaceControlMessages deletion formats (confirmed against a real
# live qualifying session):
#   "CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17"
#   "CAR 10 (GAS) LAP DELETED - TRACK LIMITS AT TURN 1 LAP 4 16:08:19 (PIT)"
# Both always carry a "LAP <n>" token identifying which lap was deleted - the reason text
# in between varies (track limits, impeding, etc.) so it's matched non-greedily rather
# than hardcoded. F1's own TimingData feed already recomputes BestLapTime/Position the
# instant a lap is deleted (confirmed live), so this regex exists only to tag the matching
# historical lap_data row is_deleted=true - not to recompute anything ourselves.
_DELETED_LAP_RE = re.compile(r"CAR (\d+) \([A-Z]{2,4}\)\s+(?:TIME [\d:.]+ DELETED|LAP DELETED)\s+-\s+.*?\bLAP (\d+)\b")

# How many drivers drop out at the end of each qualifying segment - fixed regardless of how
# many remain (this season's 22-car grid: Q1 22->16, Q2 16->10, leaving 10 for Q3, matching
# real F1 rules), so the same constant applies at both the Q1->Q2 and Q2->Q3 transitions.
QUALIFYING_ELIMINATION_COUNT = 6
# How many of a driver's most recent gap samples are kept - enough for the hover trend
# graph (5) while trend detection itself only ever looks at the most recent 3.
_GAP_HISTORY_MAXLEN = 5
_TREND_WINDOW = 3
# Minimum gap - in real *event* time (F1's own message timestamps, not wall-clock; see
# SessionState._current_event_time) - between live gap samples for the SAME driver
# (race-only: IntervalToPositionAhead is never sent during qualifying, confirmed earlier
# - see _apply_timing_data). Sampling only at lap boundaries (once every ~80-90s) meant a
# closing trend was only ever confirmed a full lap after it started, by which point the
# overtake attempt it should have warned about had often already happened or passed -
# confirmed live (Hamilton closing to 0.427s on Verstappen mid-lap never surfaced an
# alert). This throttle is deliberately time-based, not "every TimingData message" (which
# arrives multiple times a second) - sampling that fast made the strictly-monotonic trend
# check flicker on ordinary measurement noise between consecutive ticks. Event time
# (not wall-clock) so a fast-forward replay/catch-up throttles correctly by how much
# *race* time elapsed between readings, not by how fast we happened to process them.
_LIVE_GAP_SAMPLE_INTERVAL_SECONDS = 4.0


def parse_gap_seconds(value: Optional[str]) -> Optional[float]:
    """
    Parse an IntervalToPositionAhead.Value string ("+0.880") into seconds.
    Returns None rather than raising for values that aren't a plain gap -
    the race leader has no car ahead (field absent), and a lapped car's
    interval is a lap count ("1L"), neither of which is a battle-radar
    candidate.
    """
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `update` into `base` in place, returning `base`.

    Matches F1's live-timing diff semantics: nested dicts are merged key by
    key; any non-dict value (including lists and scalars) simply replaces
    whatever was there before at that key. This one function is deliberately
    reused for every per-topic merge below (TimingData, TimingAppData,
    TopThree, DriverList, TrackStatus, WeatherData, ...) instead of writing
    bespoke merge logic per topic.

    One documented exception: F1 sends some indexed collections (confirmed for
    TimingAppData.Stints) as a plain JSON array in a full-state snapshot (e.g. the
    Subscribe RPC's initial-state result - see F1SignalRStreamer._handle_subscribe_result)
    but as an index-keyed dict ("0" -> first stint, etc.) in incremental diffs. Without
    handling this, a dict-diff arriving after the array form hit the "not both dicts"
    branch and replaced the whole array wholesale - confirmed live, this silently
    discarded Compound (and everything else only ever sent once, in the array form) the
    moment any later diff touched so much as one field of the same collection.
    """
    for key, value in update.items():
        existing = base.get(key)
        if isinstance(value, dict) and isinstance(existing, list):
            existing = {str(i): item for i, item in enumerate(existing)}
        if isinstance(value, dict) and isinstance(existing, dict):
            deep_merge(existing, value)
            base[key] = existing
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
    # The gap to the car ahead at this lap boundary (Battle Radar's raw input) - persisted
    # alongside the rest of this lap's data so the closing/widening trend survives a
    # backend restart, not just held in SessionState._gap_history's in-memory buffer.
    gap_to_ahead_seconds: Optional[float] = None
    # Which qualifying segment this lap was set in ("Q1"/"Q2"/"Q3"), None for a
    # non-qualifying session - see SessionState.qualifying_part. Persisted per-lap so
    # historical analysis can tell a Q1 lap from a Q3 lap even though the live "current
    # best" display resets between segments.
    qualifying_part: Optional[str] = None


@dataclass
class QualifyingResultEntry:
    """One driver's final standing for one qualifying segment - a durable snapshot taken
    the moment that segment ends (see SessionState._snapshot_qualifying_results), so it's
    retrievable directly from Postgres afterwards instead of replaying/recomputing from the
    raw stream."""
    driver_number: int
    qualifying_part: str
    position: Optional[int]
    best_lap_seconds: Optional[float]
    gap_to_leader_seconds: Optional[float]
    eliminated: bool


@dataclass
class DeletedLap:
    """One driver+lap identified by _DELETED_LAP_RE in a RaceControlMessages entry - see
    StateDiff.deleted_laps. lap_number is F1's own cumulative NumberOfLaps count (laps are
    numbered continuously across Q1/Q2/Q3, confirmed live - only best-lap-time state
    resets per segment, not lap numbering), so it matches CompletedLap.lap_number directly."""
    driver_number: int
    lap_number: int


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
    """A newly-seen TeamRadio clip, enriched with the driver's current lap and (during
    qualifying) which segment it was captured in - neither present in the raw message."""
    driver_number: int
    utc: datetime
    path: str
    lap_number: Optional[int]
    qualifying_part: Optional[str] = None


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
    deleted_laps: List["DeletedLap"] = field(default_factory=list)
    # Populated only on the message that ends a qualifying segment (a QualifyingPart
    # transition, or SessionStatus "Finalised" for the last segment) - see
    # SessionState._snapshot_qualifying_results.
    qualifying_part_results: List["QualifyingResultEntry"] = field(default_factory=list)
    # Set uniformly by SessionState.apply(), not by individual handlers - when F1 actually
    # sent this message (real event time, not "whenever it happened to be processed").
    event_time: Optional[datetime] = None
    # Drivers whose Battle Radar status may have changed this apply() call (set or
    # cleared) - not the alerts themselves, since those live on SessionState.battle_radar
    # and diff_to_wire reads the current value for each touched driver from there.
    battle_radar_touched: List[int] = field(default_factory=list)


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
        # "Q1"/"Q2"/"Q3" for a qualifying session, None otherwise (or before the first
        # SessionData.Series entry carrying QualifyingPart arrives) - see _apply_session_data.
        self.qualifying_part: Optional[str] = None
        # Driver numbers knocked out at the end of a previous qualifying segment - see
        # _apply_session_data. Permanent for the rest of the session once added (a driver
        # eliminated in Q1 stays eliminated through Q2/Q3, they just stop receiving updates).
        self.eliminated_drivers: Set[int] = set()
        # driver_number -> gap to the session-best lap this qualifying part, in seconds
        # (0.0 for the leader). Computed entirely from our own BestLapTime state, never
        # from F1's own Stats[index].TimeDiffToFastest - see _recompute_qualifying_gaps
        # for why that field is unreliable. A driver with no valid lap yet has no entry.
        self.qualifying_gaps: Dict[int, float] = {}
        # Guards against re-persisting the same final-segment snapshot on every repeated
        # SessionStatus "Finalised" message - see _apply_session_status.
        self._final_results_captured: bool = False
        # Guards against re-flushing the formation lap on a repeated SessionStatus
        # "Started" (e.g. a red-flag restart resends it) - see _apply_session_status. A
        # second "Started" is a known, deliberately-accepted gap: without real captured
        # data for a red-flag restart to confirm F1's actual behavior there, a repeat
        # flush risks incorrectly splitting an in-progress racing lap instead.
        self._formation_lap_captured: bool = False

        # Append-only.
        self.race_control_messages: Dict[str, Any] = {}

        # Set once per session, out-of-band from an OpenF1 fetch triggered
        # when SessionInfo reveals this session's key - never comes from a
        # SignalR message itself (DriverList only ever carries a grid "Line"
        # number, no names/teams), so it isn't wired through the handler
        # dispatch below.
        self.driver_roster: Dict[int, Dict[str, Any]] = {}

        # Battle Radar: each driver's last few gap-to-car-ahead samples (lap_number,
        # gap_seconds), and the currently active alert (if any) derived from that
        # history - see _record_gap_sample/_record_live_gap_sample/_update_battle_radar.
        self._gap_history: Dict[int, Deque[Tuple[int, float]]] = {}
        self.battle_radar: Dict[int, Dict[str, Any]] = {}
        # Predicted remaining tyre strategy per driver (race/sprint only), refreshed once per
        # driver per completed lap by a detached Strands-Agent/Gemini call - see
        # predictions/tyre_strategy_prediction.py and LiveSessionPipeline._predict_and_broadcast_tyre_strategy.
        # Already wire-shaped (like battle_radar above), not the raw TyreStrategyPrediction model.
        self.tyre_strategy_predictions: Dict[int, Dict[str, Any]] = {}
        # event_time of each driver's last *live* (not lap-boundary) gap sample -
        # throttles _record_live_gap_sample, see _LIVE_GAP_SAMPLE_INTERVAL_SECONDS.
        self._last_live_gap_sample_at: Dict[int, datetime] = {}
        # Set by apply() before dispatching to a handler (see apply()'s docstring) - the
        # real event time of whatever message is currently being processed, available to
        # any handler that needs it (only _record_live_gap_sample does, today) without
        # changing every handler's call signature just to thread one optional value through.
        self._current_event_time: Optional[datetime] = None

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
            "SessionData": self._apply_session_data,
            "SessionStatus": self._apply_session_status,
            "LapCount": lambda payload: self._apply_replace(payload, self.lap_count, "LapCount"),
            "ExtrapolatedClock": lambda payload: self._apply_replace(payload, self.extrapolated_clock, "ExtrapolatedClock"),
            "RaceControlMessages": self._apply_race_control,
            "TeamRadio": self._apply_team_radio,
        }

    def apply(self, event_name: str, payload: Any, event_time: Optional[datetime] = None) -> StateDiff:
        """
        Merge one decoded SignalR message into state, returning what changed.

        `event_time` is when F1 actually sent this message (from the raw archive's own
        capture timestamp during replay/tail, or "now" for a genuinely live message) - set
        on every returned diff so a persist path that needs a real event timestamp (e.g.
        weather_snapshots.ts) never has to fall back to "whenever this happened to be
        processed", which is meaningless during a fast-forward replay/catch-up (every
        historical message would get the same "now" timestamp instead of its real one).
        """
        handler = self._handlers.get(event_name)
        if handler is None:
            logger.debug("No handler for event_name=%s, ignoring", event_name)
            return StateDiff(event_name=event_name, event_time=event_time)
        self._current_event_time = event_time
        diff = handler(payload)
        diff.event_time = event_time
        return diff

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
            "qualifying_part": self.qualifying_part,
            "eliminated_drivers": sorted(self.eliminated_drivers),
            "qualifying_gaps": dict(self.qualifying_gaps),
            "race_control_messages": self.race_control_messages,
            "driver_roster": self.driver_roster,
            "battle_radar": self.battle_radar,
            "tyre_strategy_predictions": self.tyre_strategy_predictions,
        }

    # ---- per-topic handlers ----

    def _buffer_for(self, driver_number: int) -> TelemetrySampleBuffer:
        return self._telemetry_buffers.setdefault(driver_number, TelemetrySampleBuffer())

    def _apply_timing_data(self, payload: Dict[str, Any]) -> StateDiff:
        diff = StateDiff(event_name="TimingData")
        recompute_gaps = False
        for driver_str, fields in payload.get("Lines", {}).items():
            driver_number = int(driver_str)
            deep_merge(self.drivers.setdefault(driver_number, {}), fields)
            diff.changed_driver_numbers.append(driver_number)

            if "Sectors" in fields:
                # Sector splits (S1/S2/S3) update incrementally as a lap is driven, in
                # separate messages from NumberOfLaps - stamping the lap count known at the
                # moment sectors changed lets the UI show "as of lap N" instead of implying
                # the sectors are for whatever lap happens to be displayed elsewhere by the
                # time this reaches the frontend.
                self.drivers[driver_number]["SectorsLap"] = self.drivers[driver_number].get("NumberOfLaps")

            if "BestLapTime" in fields:
                recompute_gaps = True

            if "NumberOfLaps" in fields:
                completed = self._advance_lap(driver_number, fields["NumberOfLaps"])
                if completed is not None:
                    diff.completed_laps.append(completed)

            # Live (not lap-boundary) Battle Radar sampling - race-only, since
            # IntervalToPositionAhead is never sent during qualifying (confirmed
            # earlier this session), so this is a no-op there regardless of session type.
            if "IntervalToPositionAhead" in fields and self._record_live_gap_sample(driver_number):
                diff.battle_radar_touched.append(driver_number)

        if recompute_gaps:
            self._recompute_qualifying_gaps()

        return diff

    def _recompute_qualifying_gaps(self) -> None:
        """
        Recompute every driver's gap to the session-best lap (this qualifying part) from
        our own BestLapTime state - deliberately never from F1's own
        Stats[index].TimeDiffToFastest. Confirmed live that field is unreliable two ways:
        its index isn't fixed (it shifts per qualifying part - "0" in Q1, "1" in Q2, "2" in
        Q3 - mirroring BestLapTimes' indexing), and even at the right index F1 never
        zeroes/clears it when a driver becomes the new leader, leaving whatever stale gap
        they had from their previous position (a real bug this fixes: the P1 driver
        showing a nonzero gap).

        Recomputed for every driver whenever any one driver's BestLapTime changes, since a
        new leader changes everyone's gap, not just theirs.
        """
        best_seconds: Dict[int, float] = {}
        for driver_number, fields in self.drivers.items():
            seconds = parse_lap_time_to_seconds(fields.get("BestLapTime", {}).get("Value"))
            if seconds is not None:
                best_seconds[driver_number] = seconds

        if not best_seconds:
            self.qualifying_gaps = {}
            return

        leader_seconds = min(best_seconds.values())
        self.qualifying_gaps = {
            driver_number: round(seconds - leader_seconds, 3) for driver_number, seconds in best_seconds.items()
        }

    def _advance_lap(self, driver_number: int, new_lap_number: int) -> Optional[CompletedLap]:
        """
        Detect a lap boundary: whenever a driver's NumberOfLaps increases, the
        *previous* lap just completed. Flushes and resets that driver's telemetry
        buffer. Returns None if this isn't actually an advance (first sighting of
        the driver, or a duplicate/out-of-order message).

        A CompletedLap is produced on every real advance, even when no telemetry was
        buffered for it (CarData.z not received - confirmed this can genuinely happen for
        an entire live session, not just a brief gap) - lap number/duration/gap-to-ahead
        are independent facts from telemetry and must still reach Postgres for historical
        analysis; aggregates simply come back all-None and persist_completed_lap already
        skips the lap_telemetry/lap_car_position writes when the buffer is empty.
        """
        previous_lap = self._current_lap_by_driver.get(driver_number)
        self._current_lap_by_driver[driver_number] = new_lap_number

        if previous_lap is None or new_lap_number <= previous_lap:
            return None

        # The message that announces the NEW lap number carries the just-completed
        # lap's time (and, likewise, its gap-to-car-ahead) in the same payload
        # (confirmed against real captured data: the message with NumberOfLaps=2 is
        # the one carrying LastLapTime for lap 1). `self.drivers` was already merged
        # with this message's fields by the caller. Purely a value read for persistence -
        # Battle Radar's own trend history is sampled independently, live, by
        # _record_live_gap_sample (see _apply_timing_data), not tied to lap boundaries.
        gap_to_ahead_seconds = self._current_gap_to_ahead(driver_number)

        last_lap_time = self.drivers.get(driver_number, {}).get("LastLapTime", {})
        lap_duration_seconds = parse_lap_time_to_seconds(last_lap_time.get("Value"))

        buffer = self._telemetry_buffers.pop(driver_number, None) or TelemetrySampleBuffer()
        self._telemetry_buffers[driver_number] = TelemetrySampleBuffer()

        return CompletedLap(
            driver_number=driver_number,
            lap_number=previous_lap,
            lap_duration_seconds=lap_duration_seconds,
            aggregates=buffer.compute_aggregates(DRS_ACTIVE_CODES),
            telemetry=buffer,
            gap_to_ahead_seconds=gap_to_ahead_seconds,
            qualifying_part=self.qualifying_part,
        )

    def _current_gap_to_ahead(self, driver_number: int) -> Optional[float]:
        """Parse driver_number's current IntervalToPositionAhead value, or None (leader,
        or a lapped-car interval like "1L") - a pure read with no side effects, used to
        persist "what was the gap at this lap boundary" on a CompletedLap record. Battle
        Radar's own trend state lives entirely in _record_live_gap_sample below."""
        raw_value = self.drivers.get(driver_number, {}).get("IntervalToPositionAhead", {}).get("Value")
        return parse_gap_seconds(raw_value)

    def _record_live_gap_sample(self, driver_number: int) -> bool:
        """The sole writer to _gap_history/battle_radar: throttled by real *event* time
        (_LIVE_GAP_SAMPLE_INTERVAL_SECONDS) and triggered by every live
        IntervalToPositionAhead update, not tied to lap boundaries - see that constant's
        comment for why lap-boundary-only sampling made Battle Radar too slow to catch a
        closing trend before the moment it mattered had already passed.

        Tagged with the driver's *current* (in-progress) lap number, so several samples
        can legitimately share one lap_number if multiple ticks land within it before the
        next boundary - expected and fine for both the trend check and the hover history.

        Returns whether an alert-relevant recompute actually happened (battle_radar_touched
        should fire), i.e. False when throttled.
        """
        now = self._current_event_time
        last_sampled = self._last_live_gap_sample_at.get(driver_number)
        # No event_time at all (only possible if a caller applied a message without one,
        # e.g. some test code) means there's no reliable clock to throttle against -
        # sample every time rather than silently never sampling.
        if now is not None and last_sampled is not None and (now - last_sampled).total_seconds() < _LIVE_GAP_SAMPLE_INTERVAL_SECONDS:
            return False
        if now is not None:
            self._last_live_gap_sample_at[driver_number] = now

        gap_seconds = self._current_gap_to_ahead(driver_number)
        if gap_seconds is None:
            # Leader (no car ahead) or a lapped-car interval ("1L") - never a battle-radar candidate.
            had_alert = driver_number in self.battle_radar
            self.battle_radar.pop(driver_number, None)
            return had_alert

        lap_number = self._current_lap_by_driver.get(driver_number, 0)
        history = self._gap_history.setdefault(driver_number, deque(maxlen=_GAP_HISTORY_MAXLEN))
        history.append((lap_number, gap_seconds))
        self._update_battle_radar(driver_number)
        return True

    def _update_battle_radar(self, driver_number: int) -> None:
        """
        Recompute driver_number's Battle Radar alert from its gap history.
        Requires at least 2 completed-lap samples (never fires off a single
        noisy reading) and a non-increasing gap across the last up to 3 laps,
        net strictly decreasing, before considering the driver "gaining" -
        only then do the 1.3s/2.0s thresholds decide the alert tier.
        """
        history = self._gap_history.get(driver_number)
        if history is None or len(history) < 2:
            self.battle_radar.pop(driver_number, None)
            return

        recent = list(history)[-_TREND_WINDOW:]
        gaps = [gap for _, gap in recent]
        is_gaining = gaps[-1] < gaps[0] and all(later <= earlier for earlier, later in zip(gaps, gaps[1:]))
        if not is_gaining:
            self.battle_radar.pop(driver_number, None)
            return

        current_gap = gaps[-1]
        if current_gap < BATTLE_GAP_THRESHOLD_SECONDS:
            alert_level = "battle"
        elif current_gap < UPCOMING_GAP_THRESHOLD_SECONDS:
            alert_level = "upcoming"
        else:
            self.battle_radar.pop(driver_number, None)
            return

        self.battle_radar[driver_number] = {
            "driver_number": driver_number,
            "ahead_driver_number": self._ahead_driver_number(driver_number),
            "gap_seconds": current_gap,
            "alert_level": alert_level,
            "lap_history": [{"lap_number": lap, "gap_seconds": gap} for lap, gap in history],
        }

    def _ahead_driver_number(self, driver_number: int) -> Optional[int]:
        """The driver currently one position ahead of driver_number, or None if unknown
        (position not yet seen, or driver_number is already in P1)."""
        position = self.drivers.get(driver_number, {}).get("Position")
        try:
            target_position = str(int(position) - 1)
        except (TypeError, ValueError):
            return None
        for other_number, fields in self.drivers.items():
            if other_number != driver_number and fields.get("Position") == target_position:
                return other_number
        return None

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
        lines = payload.get("Lines", {})
        if isinstance(lines, list):
            # TopThree's full-state snapshot (Subscribe RPC's initial-state result) sends
            # "Lines" as a plain array of exactly 3 entries instead of the index-keyed dict
            # incremental diffs use ("1"/"2"/"3" -> podium position, confirmed from real
            # diffs) - confirmed live, this crashed with AttributeError: 'list' object has
            # no attribute 'items' the first time an initial snapshot ever reached here.
            # 1-indexed to match the position numbering real diffs use.
            lines = {str(i + 1): entry for i, entry in enumerate(lines)}
        for driver_str, fields in lines.items():
            driver_number = int(driver_str)
            deep_merge(target.setdefault(driver_number, {}), fields)
            diff.changed_driver_numbers.append(driver_number)
        return diff

    def _apply_replace(self, payload: Dict[str, Any], target: Dict[str, Any], event_name: str) -> StateDiff:
        deep_merge(target, payload)
        return StateDiff(event_name=event_name)

    def _apply_session_status(self, payload: Dict[str, Any]) -> StateDiff:
        """
        Same replace-style merge as every other session-wide topic, plus capturing the
        last qualifying segment's final results: Status "Finalised" (confirmed live) is
        the only signal for the *last* segment ending - Q1/Q2 get their snapshot from the
        next segment's QualifyingPart transition (see _apply_session_data), but there's no
        "Q4" transition to trigger Q3's, so this is the only place it happens.
        """
        deep_merge(self.session_status, payload)
        diff = StateDiff(event_name="SessionStatus")
        if (
            payload.get("Status") == "Finalised"
            and self.qualifying_part is not None
            and not self._final_results_captured
        ):
            self._final_results_captured = True
            diff.qualifying_part_results = self._snapshot_qualifying_results(self.qualifying_part)

        if (
            payload.get("Status") == "Started"
            and self.session_info.get("Type") in ("Race", "Sprint")
            and not self._formation_lap_captured
        ):
            self._formation_lap_captured = True
            diff.completed_laps.extend(self._capture_formation_lap())

        return diff

    def _capture_formation_lap(self) -> List[CompletedLap]:
        """
        F1 never assigns a TimingData.NumberOfLaps value to the formation lap - it's
        simply absent from the feed until a driver completes the first real racing lap,
        at which point it appears already at 1 (confirmed against real captured race
        data: SessionStatus "Started" fires, then ~90s later NumberOfLaps jumps straight
        to 1 - never 0). _advance_lap's "first sighting -> no-op" branch therefore never
        fires for the formation lap, and never flushes/resets the telemetry buffer either
        - without this, all the grid/formation-lap CarData.z/Position.z samples silently
        carry over and get merged into whatever accumulates for lap 1, polluting its
        avg/max speed and DRS-active% with formation-lap pace.

        Flushes each driver's current buffer (if it actually has samples - a driver with
        nothing buffered yet gets no record, there being no independent fact-of-a-lap to
        record the way a real NumberOfLaps advance has) as its own CompletedLap tagged
        lap_number=0, then resets the buffer so lap 1 starts clean from the green flag.
        No lap_duration_seconds/gap_to_ahead_seconds - F1 reports neither for it.
        """
        completed: List[CompletedLap] = []
        for driver_number, buffer in list(self._telemetry_buffers.items()):
            if not buffer.speed and not buffer.x:
                continue
            completed.append(
                CompletedLap(
                    driver_number=driver_number,
                    lap_number=0,
                    lap_duration_seconds=None,
                    aggregates=buffer.compute_aggregates(DRS_ACTIVE_CODES),
                    telemetry=buffer,
                    gap_to_ahead_seconds=None,
                    qualifying_part=None,
                )
            )
            self._telemetry_buffers[driver_number] = TelemetrySampleBuffer()
        return completed

    def _apply_session_data(self, payload: Dict[str, Any]) -> StateDiff:
        """
        Same replace-style merge as every other session-wide topic, plus extracting the
        current qualifying segment. Confirmed live against a real Q1->Q2 transition: F1
        sends `{"Series": {"2": {"Utc": ..., "QualifyingPart": 2}}}` in this same topic at
        the exact instant the new segment begins, simultaneously with every driver's
        TimingData resetting (BestLapTime/LastLapTime/Sectors/Speeds all cleared to "" by
        F1 itself) - so self.qualifying_part and self.drivers naturally end up consistent
        without any extra reset logic here; deep_merge already reflects F1's own reset.

        A transition to Q2/Q3 also means the previous segment just ended - captures the
        bottom QUALIFYING_ELIMINATION_COUNT drivers *by their last known Position, before
        this same payload's reset wipes it* as eliminated, since F1 sends the reset in the
        same instant (no separate "eliminated" signal exists on this feed).
        """
        deep_merge(self.session_data, payload)
        diff = StateDiff(event_name="SessionData")
        series = payload.get("Series")
        if isinstance(series, dict):
            for entry in series.values():
                part = entry.get("QualifyingPart") if isinstance(entry, dict) else None
                if part is None:
                    continue
                new_part = f"Q{part}"
                if new_part != self.qualifying_part:
                    if part > 1:
                        self._eliminate_bottom_drivers()
                        # self.qualifying_part is still the *ending* part here (not yet
                        # reassigned) - the snapshot must be tagged with that, not new_part.
                        diff.qualifying_part_results = self._snapshot_qualifying_results(self.qualifying_part)
                    self.qualifying_gaps = {}
                self.qualifying_part = new_part
        return diff

    def _eliminate_bottom_drivers(self) -> None:
        """Add the bottom QUALIFYING_ELIMINATION_COUNT still-active (not already eliminated,
        Position known) drivers to self.eliminated_drivers, ranked by their current Position."""
        ranked = sorted(
            (
                (int(fields["Position"]), driver_number)
                for driver_number, fields in self.drivers.items()
                if driver_number not in self.eliminated_drivers and str(fields.get("Position", "")).isdigit()
            ),
            reverse=True,
        )
        for _, driver_number in ranked[:QUALIFYING_ELIMINATION_COUNT]:
            self.eliminated_drivers.add(driver_number)

    def _snapshot_qualifying_results(self, part: Optional[str]) -> List[QualifyingResultEntry]:
        """Every currently-known driver's final standing for `part` - see
        QualifyingResultEntry. Called the instant that segment ends (a QualifyingPart
        transition, or SessionStatus "Finalised" for the last segment - see
        _apply_session_status), so Position/BestLapTime/qualifying_gaps still reflect that
        segment's real result at the moment this runs."""
        if part is None:
            return []
        results = []
        for driver_number, fields in self.drivers.items():
            position_str = fields.get("Position")
            position = int(position_str) if str(position_str).isdigit() else None
            results.append(
                QualifyingResultEntry(
                    driver_number=driver_number,
                    qualifying_part=part,
                    position=position,
                    best_lap_seconds=parse_lap_time_to_seconds(fields.get("BestLapTime", {}).get("Value")),
                    gap_to_leader_seconds=self.qualifying_gaps.get(driver_number),
                    eliminated=driver_number in self.eliminated_drivers,
                )
            )
        return results

    def _apply_session_info(self, payload: Dict[str, Any]) -> StateDiff:
        """
        Same replace-style merge as every other session-wide topic, plus
        capturing session_key/meeting_key - confirmed from a real SessionInfo
        payload: `{"Meeting": {"Key": 1275, ...}, "Key": 9850, ...}`, where
        the top-level "Key" is the session key and "Meeting.Key" is the
        meeting key. Everything that persists to Postgres needs both.

        Also defaults qualifying_part to "Q1" the moment Type is known to be "Qualifying" -
        confirmed live that F1 never sends an explicit QualifyingPart:1 announcement (only
        the Q1->Q2 and Q2->Q3 transitions get one; Q1 is just the session's starting state
        with no signal of its own). Without this, qualifying_part stayed None for the
        entirety of Q1 - showing "Q?" in the UI instead of "Q1", and silently dropping Q1's
        results snapshot (_snapshot_qualifying_results(None) short-circuits to []).
        """
        deep_merge(self.session_info, payload)
        if "Key" in payload:
            self.session_key = payload["Key"]
        meeting = payload.get("Meeting")
        if isinstance(meeting, dict) and "Key" in meeting:
            self.meeting_key = meeting["Key"]
        if self.session_info.get("Type") == "Qualifying" and self.qualifying_part is None:
            self.qualifying_part = "Q1"
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

        deleted_laps: List[DeletedLap] = []
        for fields in messages.values():
            text = fields.get("Message") if isinstance(fields, dict) else None
            if not text:
                continue
            match = _DELETED_LAP_RE.search(text)
            if match:
                deleted_laps.append(DeletedLap(driver_number=int(match.group(1)), lap_number=int(match.group(2))))

        return StateDiff(event_name="RaceControlMessages", new_race_control_entries=new_entries, deleted_laps=deleted_laps)

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
                    qualifying_part=self.qualifying_part,
                )
            )
        return diff
