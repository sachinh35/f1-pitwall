"""
Unit tests for utils/tyre_strategy_prediction.py. build_context() is tested directly
against a real SessionState (no mocking needed - it's pure state reading). The real Gemini
API is never called - the module's Agent class is monkeypatched for predict_tyre_strategy
(see _fake_agent_class below - a fresh Agent is constructed per call by design, see
_predict_sync's docstring on why, so tests patch the constructor rather than a cached
instance, unlike tests/test_radio_analysis.py).
"""
from unittest.mock import MagicMock

import pytest

from utils import tyre_strategy_prediction
from utils.session_state import SessionState
from utils.tyre_strategy_prediction import (
    GeminiConfig,
    PredictedStint,
    RivalContext,
    TyreStrategyContext,
    TyreStrategyPrediction,
    build_context,
    predict_tyre_strategy,
)


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tyre_strategy_prediction, "_model", None)
    # Also reset the rate-limit pacing state - otherwise whichever test happens to run first
    # sets a real wall-clock timestamp that then throttles (sleeps in) every later test too.
    monkeypatch.setattr(tyre_strategy_prediction, "_last_call_started_at", None)
    yield
    monkeypatch.setattr(tyre_strategy_prediction, "_model", None)
    monkeypatch.setattr(tyre_strategy_prediction, "_last_call_started_at", None)


def _race_state() -> SessionState:
    state = SessionState()
    state.apply(
        "SessionInfo",
        {
            "Key": 11342,
            "Type": "Race",
            "Meeting": {
                "Name": "Hungarian Grand Prix",
                "Circuit": {"ShortName": "Hungaroring"},
                "Country": {"Name": "Hungary"},
            },
        },
    )
    return state


# ---- build_context: gating ----

def test_build_context_returns_none_for_qualifying() -> None:
    state = SessionState()
    state.apply("SessionInfo", {"Key": 1, "Type": "Qualifying"})
    state.apply("TimingData", {"Lines": {"44": {"Position": "1"}}})
    assert build_context(state, 44) is None


def test_build_context_returns_none_for_unknown_driver() -> None:
    state = _race_state()
    assert build_context(state, 999) is None


# ---- build_context: race fields ----

def test_build_context_reads_position_laps_and_circuit() -> None:
    state = _race_state()
    state.apply("LapCount", {"CurrentLap": 25, "TotalLaps": 70})
    state.apply("TimingData", {"Lines": {"44": {"Position": "3", "GapToLeader": "+12.500"}}})

    ctx = build_context(state, 44)

    assert ctx is not None
    assert ctx.driver_number == 44
    assert ctx.position == 3
    assert ctx.current_lap == 25
    assert ctx.total_laps == 70
    assert ctx.laps_remaining == 45
    assert ctx.meeting_name == "Hungarian Grand Prix"
    assert ctx.circuit_name == "Hungaroring"
    assert ctx.country_name == "Hungary"
    assert ctx.gap_to_leader_seconds == 12.5


def test_build_context_reads_current_stint_and_history() -> None:
    state = _race_state()
    state.apply("TimingData", {"Lines": {"44": {"Position": "1"}}})
    state.apply(
        "TimingAppData",
        {
            "Lines": {
                "44": {
                    "Stints": {
                        "0": {"Compound": "SOFT", "TotalLaps": 13},
                        "1": {"Compound": "HARD", "TotalLaps": 8},
                    }
                }
            }
        },
    )

    ctx = build_context(state, 44)

    assert ctx.current_compound == "hard"
    assert ctx.current_stint_laps == 8
    assert ctx.stint_history == [("soft", 13)]


def test_build_context_handles_no_stint_data_yet() -> None:
    state = _race_state()
    state.apply("TimingData", {"Lines": {"44": {"Position": "1"}}})
    ctx = build_context(state, 44)
    assert ctx.current_compound is None
    assert ctx.stint_history == []


def test_build_context_reads_weather_and_track_status() -> None:
    state = _race_state()
    state.apply("TimingData", {"Lines": {"44": {"Position": "1"}}})
    state.apply("WeatherData", {"AirTemp": "28.5", "TrackTemp": "45.0", "Rainfall": "1"})
    state.apply("TrackStatus", {"Status": "2", "Message": "Yellow"})

    ctx = build_context(state, 44)

    assert ctx.air_temp_c == 28.5
    assert ctx.track_temp_c == 45.0
    assert ctx.is_raining is True
    assert ctx.track_status_message == "Yellow"


def test_build_context_resolves_rival_ahead_and_behind_by_position() -> None:
    state = _race_state()
    state.apply(
        "TimingData",
        {
            "Lines": {
                "1": {"Position": "1", "GapToLeader": "0"},
                "44": {"Position": "2", "GapToLeader": "+1.500"},
                "16": {"Position": "3", "GapToLeader": "+3.000"},
            }
        },
    )
    state.apply(
        "TimingAppData",
        {
            "Lines": {
                "1": {"Stints": {"0": {"Compound": "MEDIUM", "TotalLaps": 10}}},
                "16": {"Stints": {"0": {"Compound": "SOFT", "TotalLaps": 5}}},
            }
        },
    )

    ctx = build_context(state, 44)

    assert ctx.driver_ahead == RivalContext(driver_number=1, gap_seconds=0.0, compound="medium", stint_laps=10)
    assert ctx.driver_behind == RivalContext(driver_number=16, gap_seconds=3.0, compound="soft", stint_laps=5)


def test_build_context_leader_has_no_driver_ahead() -> None:
    state = _race_state()
    state.apply("TimingData", {"Lines": {"1": {"Position": "1"}}})
    ctx = build_context(state, 1)
    assert ctx.driver_ahead is None


def test_build_context_reads_speed_vs_field_average() -> None:
    state = _race_state()
    state.apply("TimingData", {"Lines": {"44": {"Position": "1"}, "1": {"Position": "2"}}})
    state.apply("CarData.z", _car_data_payload({44: 300, 1: 280}))

    ctx = build_context(state, 44)

    assert ctx.current_speed_kmh == 300
    assert ctx.field_avg_speed_kmh == 290


def _car_data_payload(speeds: dict) -> dict:
    import base64
    import json
    import zlib

    entries = {
        str(num): {"Channels": {"0": 11000, "2": speed, "3": 6, "4": 80, "5": 0, "45": 0}}
        for num, speed in speeds.items()
    }
    raw = json.dumps({"Entries": [{"Utc": "2026-07-26T13:00:00Z", "Cars": entries}]}).encode()
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(raw) + compressor.flush()
    return base64.b64encode(compressed).decode()


# ---- to_prompt ----

def test_to_prompt_includes_key_facts() -> None:
    ctx = TyreStrategyContext(
        driver_number=44,
        position=3,
        current_lap=25,
        total_laps=70,
        laps_remaining=45,
        meeting_name="Hungarian Grand Prix",
        circuit_name="Hungaroring",
        country_name="Hungary",
        track_status_message="AllClear",
        air_temp_c=28.0,
        track_temp_c=45.0,
        is_raining=False,
        current_compound="hard",
        current_stint_laps=8,
        stint_history=[("soft", 13)],
    )
    prompt = ctx.to_prompt()
    assert "Hungaroring" in prompt
    assert "Hungary" in prompt
    assert "P3" in prompt
    assert "45" in prompt  # laps remaining
    assert "hard" in prompt
    assert "soft for 13 laps" in prompt


def test_to_prompt_handles_missing_data_gracefully() -> None:
    ctx = TyreStrategyContext(
        driver_number=1,
        position=None,
        current_lap=None,
        total_laps=None,
        laps_remaining=None,
        meeting_name=None,
        circuit_name=None,
        country_name=None,
        track_status_message=None,
        air_temp_c=None,
        track_temp_c=None,
        is_raining=None,
        current_compound=None,
        current_stint_laps=None,
        stint_history=[],
    )
    prompt = ctx.to_prompt()
    assert "unknown" in prompt
    assert "still on the starting set" in prompt


# ---- predict_tyre_strategy ----

def _fake_agent_class(returned: TyreStrategyPrediction) -> MagicMock:
    """A fresh Agent is constructed per call (see _predict_sync's docstring: a shared/cached
    Agent raises ConcurrencyException on overlapping calls, confirmed live against real
    concurrent lap completions) - so tests patch the Agent *class* (constructor), not a
    cached instance, and assert against the instance it returns."""
    instance = MagicMock()
    result = MagicMock()
    result.structured_output = returned
    instance.return_value = result
    agent_class = MagicMock(return_value=instance)
    return agent_class


_SAMPLE_CONTEXT = TyreStrategyContext(
    driver_number=44, position=3, current_lap=25, total_laps=70, laps_remaining=45,
    meeting_name="Hungarian Grand Prix", circuit_name="Hungaroring", country_name="Hungary",
    track_status_message="AllClear", air_temp_c=28.0, track_temp_c=45.0, is_raining=False,
    current_compound="hard", current_stint_laps=8, stint_history=[],
)


@pytest.mark.asyncio
async def test_predict_tyre_strategy_returns_agents_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = TyreStrategyPrediction(
        predicted_stints=[
            PredictedStint(stint_number=1, compound="hard", predicted_total_laps=30),
            PredictedStint(stint_number=2, compound="medium", predicted_total_laps=40),
        ],
        safety_car_note="Low historical SC risk at this circuit.",
        summary="One more stop, likely onto medium around lap 30.",
    )
    agent_class = _fake_agent_class(expected)
    monkeypatch.setattr(tyre_strategy_prediction, "Agent", agent_class)
    monkeypatch.setattr(tyre_strategy_prediction, "_get_model", lambda: "fake-model")

    result = await predict_tyre_strategy(_SAMPLE_CONTEXT)

    assert result == expected
    agent_instance = agent_class.return_value
    prompt, kwargs = agent_instance.call_args.args[0], agent_instance.call_args.kwargs
    assert "Hungaroring" in prompt
    assert kwargs["structured_output_model"] is TyreStrategyPrediction
    assert kwargs["system_prompt"] == tyre_strategy_prediction._SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_predict_tyre_strategy_constructs_a_fresh_agent_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: a shared/cached Agent raised strands.types.exceptions.ConcurrencyException
    ("Agent is already processing a request") the moment two drivers completed a lap within a
    couple of seconds of each other - confirmed live against the real race feed. Each call must
    get its own Agent instance."""
    expected = TyreStrategyPrediction(predicted_stints=[], safety_car_note="x", summary="y")
    agent_class = _fake_agent_class(expected)
    monkeypatch.setattr(tyre_strategy_prediction, "Agent", agent_class)
    monkeypatch.setattr(tyre_strategy_prediction, "_get_model", lambda: "fake-model")
    monkeypatch.setattr(tyre_strategy_prediction, "_MIN_CALL_INTERVAL_SECONDS", 0.0)

    await predict_tyre_strategy(_SAMPLE_CONTEXT)
    await predict_tyre_strategy(_SAMPLE_CONTEXT)

    assert agent_class.call_count == 2


@pytest.mark.asyncio
async def test_predict_tyre_strategy_propagates_agent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise RuntimeError("Gemini quota exceeded")

    agent_class = MagicMock(return_value=MagicMock(side_effect=_raise))
    monkeypatch.setattr(tyre_strategy_prediction, "Agent", agent_class)
    monkeypatch.setattr(tyre_strategy_prediction, "_get_model", lambda: "fake-model")

    with pytest.raises(RuntimeError, match="Gemini quota exceeded"):
        await predict_tyre_strategy(_SAMPLE_CONTEXT)


def test_get_model_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GeminiConfig, "API_KEY", None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        tyre_strategy_prediction._get_model()


# ---- rate-limit pacing (Gemini free tier: 15 req/min, confirmed live via a real 429) ----

@pytest.mark.asyncio
async def test_predict_tyre_strategy_paces_back_to_back_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tyre_strategy_prediction, "_MIN_CALL_INTERVAL_SECONDS", 0.05)
    agent_class = _fake_agent_class(TyreStrategyPrediction(predicted_stints=[], safety_car_note="x", summary="y"))
    monkeypatch.setattr(tyre_strategy_prediction, "Agent", agent_class)
    monkeypatch.setattr(tyre_strategy_prediction, "_get_model", lambda: "fake-model")

    import time

    start = time.monotonic()
    await predict_tyre_strategy(_SAMPLE_CONTEXT)
    await predict_tyre_strategy(_SAMPLE_CONTEXT)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.05


@pytest.mark.asyncio
async def test_predict_tyre_strategy_does_not_wait_before_the_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tyre_strategy_prediction, "_MIN_CALL_INTERVAL_SECONDS", 10.0)
    agent_class = _fake_agent_class(TyreStrategyPrediction(predicted_stints=[], safety_car_note="x", summary="y"))
    monkeypatch.setattr(tyre_strategy_prediction, "Agent", agent_class)
    monkeypatch.setattr(tyre_strategy_prediction, "_get_model", lambda: "fake-model")

    import asyncio as _asyncio

    await _asyncio.wait_for(predict_tyre_strategy(_SAMPLE_CONTEXT), timeout=1.0)


def test_get_model_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GeminiConfig, "API_KEY", "fake-key")
    constructed = []

    def _fake_gemini_model(**kwargs):
        constructed.append(kwargs)
        return "fake-model"

    monkeypatch.setattr(tyre_strategy_prediction, "GeminiModel", _fake_gemini_model)

    first = tyre_strategy_prediction._get_model()
    second = tyre_strategy_prediction._get_model()

    assert first is second
    assert len(constructed) == 1
