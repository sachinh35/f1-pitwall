"""
Predicts each driver's remaining tyre strategy via a Strands Agent backed by Google
Gemini - race mode only (see build_context: qualifying sessions never produce a context,
since GapToLeader/IntervalToPositionAhead/lap-count-remaining are all race-only concepts,
confirmed live earlier this session).

Triggered once per driver per completed lap (see LiveSessionPipeline.process_message),
not on every message, so the prediction is always as fresh as the driver's last full lap
without hammering the Gemini API on every timing tick. Formation-lap (lap_number == 0)
completions are skipped by the caller - a formation lap isn't representative racing pace.

Follows the exact same thin-wrapper-around-one-function shape as utils/radio_analysis.py:
tests monkeypatch _get_agent() rather than hitting the real Gemini API (see
tests/test_tyre_strategy_prediction.py).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from strands import Agent
from strands.models.gemini import GeminiModel

from config.gemini_config import GeminiConfig
from utils.session_state import SessionState, parse_gap_seconds

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an F1 race strategist predicting how a driver's tyre strategy will play out for the
rest of the race. You will be given: laps remaining, the driver's position and current tyre stint, their
complete stint history so far this race, the circuit name and country, current weather, the current track
status (green/yellow/safety car/VSC), the driver's on-track rivals (car ahead and car behind, with gaps and
their tyre compounds), and a speed comparison against the field average.

Reason step by step before answering: (1) how many laps is the current compound realistically good for at
this circuit and these conditions, factoring in track temperature and any rain; (2) drawing on your own
knowledge of this circuit's real-world Grand Prix history, how likely is a safety car or VSC in the
remaining laps, and would that likely trigger an early/opportunistic pit stop that changes the calculus;
(3) is the driver defending or attacking based on the gaps to the car ahead/behind, and would an undercut or
overcut make sense given that; (4) is their current pace (speed vs field average) consistent with tyres that
still have life, or already degrading.

Then predict the full remaining strategy as an ordered list of stints starting with the stint currently on
the car (stint_number=1) through to the chequered flag. Compound must be one of: soft, medium, hard,
intermediate, wet. predicted_total_laps is the total laps you expect that whole stint to run for (not just
the remaining laps) - for the current stint, this includes the laps already completed on it. If the
driver's remaining race distance realistically fits on the current set with no further stop, return exactly
one stint. Keep the summary and safety_car_note each to one short sentence."""


class PredictedStint(BaseModel):
    stint_number: int = Field(description="1-indexed order of this stint, starting from the one currently on the car")
    compound: Literal["soft", "medium", "hard", "intermediate", "wet"]
    predicted_total_laps: int = Field(description="Total laps this stint is predicted to run for, start to pit/finish")


class TyreStrategyPrediction(BaseModel):
    predicted_stints: List[PredictedStint] = Field(description="Ordered from the current stint through to the finish")
    safety_car_note: str = Field(description="One short sentence on how this circuit's safety car history factored in")
    summary: str = Field(description="One short sentence summarizing the predicted strategy and why")


@dataclass
class RivalContext:
    driver_number: int
    gap_seconds: Optional[float]
    compound: Optional[str]
    stint_laps: Optional[int]


@dataclass
class TyreStrategyContext:
    driver_number: int
    position: Optional[int]
    current_lap: Optional[int]
    total_laps: Optional[int]
    laps_remaining: Optional[int]
    meeting_name: Optional[str]
    circuit_name: Optional[str]
    country_name: Optional[str]
    track_status_message: Optional[str]
    air_temp_c: Optional[float]
    track_temp_c: Optional[float]
    is_raining: Optional[bool]
    current_compound: Optional[str]
    current_stint_laps: Optional[int]
    # Completed stints only (excludes the current, in-progress one) - (compound, total_laps).
    stint_history: List[tuple] = field(default_factory=list)
    current_speed_kmh: Optional[float] = None
    field_avg_speed_kmh: Optional[float] = None
    gap_to_leader_seconds: Optional[float] = None
    interval_ahead_seconds: Optional[float] = None
    driver_ahead: Optional[RivalContext] = None
    driver_behind: Optional[RivalContext] = None

    def to_prompt(self) -> str:
        def fmt(value: Any, suffix: str = "") -> str:
            return "unknown" if value is None else f"{value}{suffix}"

        def fmt_rival(label: str, rival: Optional[RivalContext]) -> str:
            if rival is None:
                return f"{label}: none (track limit)"
            return (
                f"{label}: car #{rival.driver_number}, gap {fmt(rival.gap_seconds, 's')}, "
                f"on {fmt(rival.compound)} ({fmt(rival.stint_laps, ' laps')} on that set)"
            )

        stint_history_text = (
            "; ".join(f"{compound} for {laps if laps is not None else 'an unknown number of'} laps" for compound, laps in self.stint_history)
            or "none yet - still on the starting set"
        )

        speed_comparison = "unknown"
        if self.current_speed_kmh is not None and self.field_avg_speed_kmh is not None:
            delta = self.current_speed_kmh - self.field_avg_speed_kmh
            speed_comparison = f"{self.current_speed_kmh:.0f} km/h ({delta:+.0f} km/h vs field average {self.field_avg_speed_kmh:.0f} km/h)"

        return f"""Race: {fmt(self.meeting_name)} at {fmt(self.circuit_name)}, {fmt(self.country_name)}.
Lap {fmt(self.current_lap)} of {fmt(self.total_laps)} ({fmt(self.laps_remaining)} laps remaining).
Track status: {fmt(self.track_status_message)}. Air temp {fmt(self.air_temp_c, "C")}, track temp {fmt(self.track_temp_c, "C")}, raining: {fmt(self.is_raining)}.

Driver #{self.driver_number}, currently P{fmt(self.position)}.
Gap to leader: {fmt(self.gap_to_leader_seconds, "s")}. Interval to car ahead: {fmt(self.interval_ahead_seconds, "s")}.
Current tyre: {fmt(self.current_compound)}, {fmt(self.current_stint_laps, " laps")} into this stint.
Stint history so far this race: {stint_history_text}.
Current speed: {speed_comparison}.
{fmt_rival("Car ahead", self.driver_ahead)}
{fmt_rival("Car behind", self.driver_behind)}"""


def _compound_of(stint_info: Optional[Dict[str, Any]]) -> Optional[str]:
    if not stint_info:
        return None
    compound = stint_info.get("Compound")
    return compound.lower() if compound else None


def _driver_stint_summary(state: SessionState, driver_number: int) -> tuple:
    """(current_compound, current_stint_laps, completed_stint_history) for driver_number,
    reusing the exact same Stints-index-ordering logic as TimingTower's compoundHistory on
    the frontend (see TimingTower.tsx) - the last index is the in-progress stint, everything
    before it is history."""
    stints = state.timing_app_data.get(driver_number, {}).get("Stints", {})
    if not stints:
        return None, None, []
    ordered = sorted(stints.items(), key=lambda kv: int(kv[0]))
    history = [(_compound_of(info) or "unknown", info.get("TotalLaps")) for _, info in ordered[:-1]]
    last_info = ordered[-1][1]
    return _compound_of(last_info), last_info.get("TotalLaps"), history


def _rival_context(state: SessionState, driver_number: int, target_position: Optional[int]) -> Optional[RivalContext]:
    if target_position is None:
        return None
    for other_number, fields in state.drivers.items():
        if other_number == driver_number:
            continue
        other_position = fields.get("Position")
        if other_position is None or int(other_position) != target_position:
            continue
        compound, stint_laps, _ = _driver_stint_summary(state, other_number)
        gap = parse_gap_seconds(fields.get("GapToLeader"))
        return RivalContext(driver_number=other_number, gap_seconds=gap, compound=compound, stint_laps=stint_laps)
    return None


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_context(state: SessionState, driver_number: int) -> Optional[TyreStrategyContext]:
    """
    Gather every variable the strategy prediction needs for one driver from the current
    SessionState - race mode only. Returns None (skip prediction, not an error) when the
    session isn't a race/sprint, or when this driver hasn't been seen in TimingData yet.
    """
    if state.session_info.get("Type") not in ("Race", "Sprint"):
        return None

    driver = state.drivers.get(driver_number)
    if driver is None:
        return None

    position_raw = driver.get("Position")
    position = int(position_raw) if position_raw not in (None, "") else None

    current_lap = state.lap_count.get("CurrentLap")
    total_laps = state.lap_count.get("TotalLaps")
    laps_remaining = total_laps - current_lap if current_lap is not None and total_laps is not None else None

    meeting = state.session_info.get("Meeting") or {}
    circuit_name = (meeting.get("Circuit") or {}).get("ShortName")
    country_name = (meeting.get("Country") or {}).get("Name")

    weather = state.weather
    rainfall = _safe_float(weather.get("Rainfall"))

    current_compound, current_stint_laps, stint_history = _driver_stint_summary(state, driver_number)

    telemetry = state.latest_telemetry_sample(driver_number)
    current_speed = telemetry.get("speed_kmh") if telemetry else None
    field_speeds = [
        sample["speed_kmh"]
        for other_number in state.drivers
        if (sample := state.latest_telemetry_sample(other_number)) is not None
    ]
    field_avg_speed = sum(field_speeds) / len(field_speeds) if field_speeds else None

    driver_ahead = _rival_context(state, driver_number, position - 1 if position is not None else None)
    driver_behind = _rival_context(state, driver_number, position + 1 if position is not None else None)

    return TyreStrategyContext(
        driver_number=driver_number,
        position=position,
        current_lap=current_lap,
        total_laps=total_laps,
        laps_remaining=laps_remaining,
        meeting_name=meeting.get("Name"),
        circuit_name=circuit_name,
        country_name=country_name,
        track_status_message=state.track_status.get("Message"),
        air_temp_c=_safe_float(weather.get("AirTemp")),
        track_temp_c=_safe_float(weather.get("TrackTemp")),
        is_raining=None if rainfall is None else rainfall > 0,
        current_compound=current_compound,
        current_stint_laps=current_stint_laps,
        stint_history=stint_history,
        current_speed_kmh=current_speed,
        field_avg_speed_kmh=field_avg_speed,
        gap_to_leader_seconds=parse_gap_seconds(driver.get("GapToLeader")),
        interval_ahead_seconds=parse_gap_seconds((driver.get("IntervalToPositionAhead") or {}).get("Value")),
        driver_ahead=driver_ahead,
        driver_behind=driver_behind,
    )


_model: Optional[GeminiModel] = None


def _get_model() -> GeminiModel:
    """Lazily construct the cached GeminiModel config - not at import time, so importing this
    module never requires GEMINI_API_KEY to be set (only actually calling predict_tyre_strategy
    does).

    Deliberately NOT a cached Agent (unlike utils/radio_analysis.py's _get_agent): a Strands
    Agent instance raises strands.types.exceptions.ConcurrencyException on a second overlapping
    call ("Agent is already processing a request") - confirmed live, this fires constantly
    here since multiple drivers routinely complete their lap within a second or two of each
    other, each spawning a concurrent prediction. The GeminiModel config itself is stateless
    and safe to share; a fresh, cheap Agent wrapper is built per call in _predict_sync instead."""
    global _model
    if _model is None:
        if not GeminiConfig.API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set - copy .env.example to .env and fill it in")
        _model = GeminiModel(
            client_args={"api_key": GeminiConfig.API_KEY},
            model_id=GeminiConfig.MODEL_ID,
            params={"temperature": 0.3, "max_output_tokens": 1024},
        )
    return _model


def _predict_sync(context: TyreStrategyContext) -> TyreStrategyPrediction:
    agent = Agent(model=_get_model())
    result = agent(context.to_prompt(), system_prompt=_SYSTEM_PROMPT, structured_output_model=TyreStrategyPrediction)
    return result.structured_output


# Gemini's free tier caps generate_content at 15 requests/minute (confirmed live via a real
# 429 ResourceExhausted response) - with ~20 drivers each completing a lap roughly every 90s,
# demand sits right at that ceiling even under even spacing, and bursts past it easily (a
# safety car restart bunches the whole field's lap completions within a few seconds of each
# other). Rather than let calls fail outright under a burst - directly defeating the point of
# refreshing every lap - callers are paced to a safe minimum interval so they queue and drain
# within quota instead. Predictions lag behind real-time under a burst rather than being lost.
_MIN_CALL_INTERVAL_SECONDS = 4.5
_rate_limit_lock = asyncio.Lock()
_last_call_started_at: Optional[float] = None


async def _throttle() -> None:
    global _last_call_started_at
    async with _rate_limit_lock:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if _last_call_started_at is not None:
            wait = _MIN_CALL_INTERVAL_SECONDS - (now - _last_call_started_at)
            if wait > 0:
                await asyncio.sleep(wait)
        _last_call_started_at = loop.time()


async def predict_tyre_strategy(context: TyreStrategyContext) -> TyreStrategyPrediction:
    """
    Predict one driver's remaining tyre strategy. Paced by _throttle() to stay within
    Gemini's rate limit (see above), then run via the default executor since the Strands
    agent call itself is synchronous/blocking (network I/O) - same reasoning as
    whisper_transcriber.transcribe() and radio_analysis.analyze_transcript().
    """
    await _throttle()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _predict_sync, context)
