"""
Unit tests for utils/live_session_pipeline.py - the write-path orchestration
(archive -> merge -> broadcast -> detached persist) that both the live
SignalR stream and replay drive identically. Persistence/radio functions are
mocked here; each is already covered by its own tests (test_live_persistence.py,
test_team_radio_pipeline.py) plus the real end-to-end verification run
against Postgres during Milestone 6/7.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from openf1_pydantic_models.f1_drivers import DriverInfo
from openf1_pydantic_models.f1_sessions import F1Session
from utils import live_session_pipeline as pipeline_module
from utils.live_session_pipeline import LiveSessionPipeline, diff_to_wire
from utils.session_state import RadioCapture, SessionState, StateDiff

_SAMPLE_CONFIRMED_ROSTER = [
    ConfirmedRosterEntry(driver_number=1, tla="NOR", full_name="Lando Norris", team_name="McLaren", team_colour="#F58020"),
    ConfirmedRosterEntry(driver_number=81, tla="OWA", full_name="Pato O'Ward", team_name="McLaren", team_colour="#F58020"),
]

_SAMPLE_DRIVER = DriverInfo(
    meeting_key=1275,
    session_key=9850,
    driver_number=1,
    broadcast_name="M VERSTAPPEN",
    full_name="Max Verstappen",
    name_acronym="VER",
    team_name="Red Bull Racing",
    team_colour="3671C6",
    first_name="Max",
    last_name="Verstappen",
    headshot_url="https://example.com/ver.png",
    country_code="NED",
)

_SAMPLE_SESSION_META = F1Session(
    circuit_key=63,
    circuit_short_name="Losail",
    country_code="QAT",
    country_key=10,
    country_name="Qatar",
    date_end=datetime(2025, 11, 30, 18, 0, 0),
    date_start=datetime(2025, 11, 30, 16, 0, 0),
    gmt_offset="03:00:00",
    location="Lusail",
    meeting_key=1275,
    session_key=9850,
    session_name="Race",
    session_type="Race",
    year=2025,
)


async def _drain_background_tasks(pipeline: LiveSessionPipeline) -> None:
    """Let any asyncio.create_task-spawned work (persist calls) finish before asserting on it."""
    if pipeline._background_tasks:
        await asyncio.gather(*list(pipeline._background_tasks))


@pytest.fixture(autouse=True)
def _mock_persistence(monkeypatch: pytest.MonkeyPatch):
    """Every test gets fresh, no-op mocks for everything process_message can spawn.

    fetch_session_metadata/fetch_driver_roster default to "nothing found" (None / empty list) so
    SessionInfo-triggered tests never make a real OpenF1 network call; tests that care about the
    roster-fetch/broadcast path override these explicitly.
    """
    monkeypatch.setattr(pipeline_module, "persist_completed_lap", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_weather_snapshot", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_race_control_entry", AsyncMock())
    monkeypatch.setattr(pipeline_module, "mark_lap_deleted", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_qualifying_results", AsyncMock())
    monkeypatch.setattr(pipeline_module, "process_radio_capture", AsyncMock())
    monkeypatch.setattr(pipeline_module, "predict_tyre_strategy", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_session_metadata", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_driver_roster", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_confirmed_driver_roster", AsyncMock())
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", AsyncMock(return_value=[]))
    monkeypatch.setattr(pipeline_module, "fetch_total_laps", AsyncMock(return_value=None))
    # No token saved by default - keeps tests deterministic regardless of the machine's real
    # local F1TV auth state (see utils/f1_auth.py). Tests that care about the auth-headers
    # path override this explicitly.
    monkeypatch.setattr(pipeline_module.f1_auth, "get_saved_token", lambda: None)
    monkeypatch.setattr(pipeline_module, "persist_total_laps", AsyncMock())


def test_subscribe_delivers_initial_snapshot() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-1")
    subscriber_id, queue = pipeline.subscribe()

    assert not queue.empty()
    message = queue.get_nowait()
    assert message["event"] == "snapshot"
    assert message["data"] == pipeline.state.snapshot()
    assert subscriber_id in pipeline._subscribers


def test_unsubscribe_removes_subscriber() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-2")
    subscriber_id, _ = pipeline.subscribe()
    pipeline.unsubscribe(subscriber_id)
    assert subscriber_id not in pipeline._subscribers


@pytest.mark.asyncio
async def test_process_message_broadcasts_resolved_state_to_all_subscribers() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-3")
    _, queue1 = pipeline.subscribe()
    _, queue2 = pipeline.subscribe()
    # Drain the initial snapshot each subscriber gets.
    queue1.get_nowait()
    queue2.get_nowait()

    await pipeline.process_message("WeatherData", {"AirTemp": "25.1"})

    for queue in (queue1, queue2):
        message = queue.get_nowait()
        assert message["event"] == "WeatherData"
        assert message["data"] == {"weather": {"AirTemp": "25.1"}}


@pytest.mark.asyncio
async def test_process_message_unknown_event_does_not_raise() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-4")
    # Should simply not crash - Heartbeat has no registered handler.
    await pipeline.process_message("Heartbeat", {"Utc": "2025-01-01T00:00:00Z"})


@pytest.mark.asyncio
async def test_process_message_swallows_a_bad_payload_without_taking_down_the_pipeline() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-5")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain snapshot

    # TimingData handler expects a dict with .get("Lines", {}) - this should be
    # caught and logged, not raised, and the pipeline should keep working after.
    await pipeline.process_message("TimingData", "not-a-dict")
    assert queue.empty()  # nothing broadcast for the failed message

    await pipeline.process_message("WeatherData", {"AirTemp": "20.0"})
    message = queue.get_nowait()
    assert message["event"] == "WeatherData"


@pytest.mark.asyncio
async def test_completed_lap_triggers_detached_persist_with_session_and_meeting_key() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-6")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})

    # Lap 1, first sighting - no completion possible yet.
    await pipeline.process_message("TimingData", {"Lines": {"1": {"NumberOfLaps": 1}}})
    # Give the driver some buffered telemetry so the next transition has something to flush.
    pipeline.state._buffer_for(1).add_car_sample(
        utc=datetime(2025, 1, 1), rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    await pipeline.process_message("TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}})

    await _drain_background_tasks(pipeline)
    pipeline_module.persist_completed_lap.assert_awaited_once()
    call_args = pipeline_module.persist_completed_lap.call_args.args
    assert call_args[0] == 9850  # session_key
    assert call_args[1] == 1275  # meeting_key


@pytest.mark.asyncio
async def test_completed_lap_persist_skipped_when_session_key_unknown() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-7")
    # No SessionInfo processed - session_key stays None.
    await pipeline.process_message("TimingData", {"Lines": {"1": {"NumberOfLaps": 1}}})
    pipeline.state._buffer_for(1).add_car_sample(
        utc=datetime(2025, 1, 1), rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )
    await pipeline.process_message("TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}})

    await _drain_background_tasks(pipeline)
    pipeline_module.persist_completed_lap.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_lap_triggers_tyre_strategy_prediction_in_race_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.tyre_strategy_prediction import PredictedStint, TyreStrategyPrediction

    prediction = TyreStrategyPrediction(
        predicted_stints=[PredictedStint(stint_number=1, compound="hard", predicted_total_laps=30)],
        safety_car_note="Low SC risk historically at this circuit.",
        summary="Expected to run hards to the finish.",
    )
    monkeypatch.setattr(pipeline_module, "predict_tyre_strategy", AsyncMock(return_value=prediction))

    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-1")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain initial snapshot

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Race", "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain SessionInfo broadcast

    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1", "NumberOfLaps": 1}}})
    queue.get_nowait()
    await pipeline.process_message(
        "TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}}
    )
    queue.get_nowait()  # drain the TimingData broadcast itself

    await _drain_background_tasks(pipeline)

    pipeline_module.predict_tyre_strategy.assert_awaited_once()
    context = pipeline_module.predict_tyre_strategy.call_args.args[0]
    assert context.driver_number == 1

    assert pipeline.state.tyre_strategy_predictions[1]["summary"] == "Expected to run hards to the finish."
    assert pipeline.state.tyre_strategy_predictions[1]["generated_at_lap"] == 1
    assert pipeline.state.tyre_strategy_predictions[1]["predicted_stints"] == [
        {"stint_number": 1, "compound": "hard", "predicted_total_laps": 30}
    ]

    message = queue.get_nowait()
    assert message["event"] == "TYRE_STRATEGY_PREDICTION"
    assert message["data"]["driver_number"] == 1
    assert message["data"]["prediction"]["summary"] == "Expected to run hards to the finish."


@pytest.mark.asyncio
async def test_completed_lap_does_not_trigger_tyre_strategy_prediction_in_qualifying() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-2")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Qualifying", "Meeting": {"Key": 1275}})

    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1", "NumberOfLaps": 1}}})
    await pipeline.process_message(
        "TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}}
    )

    await _drain_background_tasks(pipeline)
    pipeline_module.predict_tyre_strategy.assert_not_awaited()
    assert pipeline.state.tyre_strategy_predictions == {}


@pytest.mark.asyncio
async def test_formation_lap_does_not_trigger_tyre_strategy_prediction() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-3")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Race", "Meeting": {"Key": 1275}})
    pipeline.state._buffer_for(1).add_car_sample(
        utc=datetime(2025, 1, 1), rpm=11000, speed_kmh=300, gear=8, throttle_pct=100, brake_pct=0, drs=12,
    )

    # SessionStatus "Started" on a Race produces a lap_number=0 formation-lap CompletedLap
    # (see SessionState._capture_formation_lap) - must not trigger a strategy prediction.
    await pipeline.process_message("SessionStatus", {"Status": "Started"})

    await _drain_background_tasks(pipeline)
    pipeline_module.predict_tyre_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_tyre_strategy_prediction_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline_module, "predict_tyre_strategy", AsyncMock(side_effect=RuntimeError("Gemini quota exceeded"))
    )
    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-4")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Race", "Meeting": {"Key": 1275}})

    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1", "NumberOfLaps": 1}}})
    await pipeline.process_message(
        "TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}}
    )

    await _drain_background_tasks(pipeline)  # must not raise
    assert pipeline.state.tyre_strategy_predictions == {}


@pytest.mark.asyncio
async def test_stale_tyre_strategy_prediction_is_skipped_once_the_race_has_moved_on() -> None:
    """Regression test: re-attaching to an in-progress race replays the whole archive from
    lap 1 before catching up to "now", queuing one prediction per driver per historical lap
    behind the rate limiter (see tyre_strategy_prediction._throttle). Confirmed live: without
    this check, the queue ground through history at ~1 call/4.5s instead of ever reflecting
    the real, current lap. A request for a lap far behind the session's current lap by the
    time it's about to run must be skipped, not computed."""
    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-stale")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Race", "Meeting": {"Key": 1275}})

    # Driver 1 completes lap 1 (NumberOfLaps 1 -> 2)...
    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1", "NumberOfLaps": 1}}})
    await pipeline.process_message(
        "TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}}
    )
    # ...but by the time the queued/rate-limited prediction task actually runs, the race has
    # already moved on well past that lap (a fast catch-up replay outrunning the throttled queue).
    await pipeline.process_message("LapCount", {"CurrentLap": 40})

    await _drain_background_tasks(pipeline)
    pipeline_module.predict_tyre_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_tyre_strategy_prediction_still_runs_when_only_slightly_behind_current_lap() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-tyre-strategy-fresh")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Type": "Race", "Meeting": {"Key": 1275}})

    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1", "NumberOfLaps": 1}}})
    await pipeline.process_message(
        "TimingData", {"Lines": {"1": {"NumberOfLaps": 2, "LastLapTime": {"Value": "1:27.150"}}}}
    )
    await pipeline.process_message("LapCount", {"CurrentLap": 2})  # only 1 lap behind - still fresh

    await _drain_background_tasks(pipeline)
    pipeline_module.predict_tyre_strategy.assert_awaited_once()


@pytest.mark.asyncio
async def test_radio_capture_includes_session_path_from_session_info(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = LiveSessionPipeline(stream_id="test-radio-session-path")
    await pipeline.process_message(
        "SessionInfo", {"Key": 9850, "Path": "2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/"}
    )
    await pipeline.process_message(
        "TeamRadio", {"Captures": [{"Utc": "2025-01-01T00:00:00Z", "RacingNumber": "1", "Path": "TeamRadio/x.mp3"}]}
    )
    await _drain_background_tasks(pipeline)

    assert pipeline_module.process_radio_capture.call_args.kwargs["session_path"] == (
        "2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/"
    )


@pytest.mark.asyncio
async def test_new_radio_capture_triggers_detached_download_pipeline() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-8")
    await pipeline.process_message("SessionInfo", {"Key": 9850})
    await pipeline.process_message(
        "TeamRadio", {"Captures": [{"Utc": "2025-01-01T00:00:00Z", "RacingNumber": "1", "Path": "TeamRadio/x.mp3"}]}
    )

    await _drain_background_tasks(pipeline)
    pipeline_module.process_radio_capture.assert_awaited_once()
    assert pipeline_module.process_radio_capture.call_args.kwargs["session_key"] == 9850
    # No F1TV token saved (autouse fixture default) - downloads still get attempted, unauthenticated.
    assert pipeline_module.process_radio_capture.call_args.kwargs["auth_headers"] is None


@pytest.mark.asyncio
async def test_radio_capture_includes_bearer_auth_header_when_a_valid_token_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module.f1_auth, "get_saved_token", lambda: "fake.jwt.token")
    monkeypatch.setattr(pipeline_module.f1_auth, "validate_subscription_token", lambda token: True)

    pipeline = LiveSessionPipeline(stream_id="test-radio-auth-1")
    await pipeline.process_message("SessionInfo", {"Key": 9850})
    await pipeline.process_message(
        "TeamRadio", {"Captures": [{"Utc": "2025-01-01T00:00:00Z", "RacingNumber": "1", "Path": "TeamRadio/x.mp3"}]}
    )
    await _drain_background_tasks(pipeline)

    assert pipeline_module.process_radio_capture.call_args.kwargs["auth_headers"] == {
        "Authorization": "Bearer fake.jwt.token"
    }


@pytest.mark.asyncio
async def test_radio_capture_omits_auth_header_when_saved_token_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module.f1_auth, "get_saved_token", lambda: "expired.jwt.token")
    monkeypatch.setattr(pipeline_module.f1_auth, "validate_subscription_token", lambda token: False)

    pipeline = LiveSessionPipeline(stream_id="test-radio-auth-2")
    await pipeline.process_message("SessionInfo", {"Key": 9850})
    await pipeline.process_message(
        "TeamRadio", {"Captures": [{"Utc": "2025-01-01T00:00:00Z", "RacingNumber": "1", "Path": "TeamRadio/x.mp3"}]}
    )
    await _drain_background_tasks(pipeline)

    assert pipeline_module.process_radio_capture.call_args.kwargs["auth_headers"] is None


@pytest.mark.asyncio
async def test_weather_and_race_control_persist_immediately_not_on_lap_boundary() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})

    await pipeline.process_message("WeatherData", {"AirTemp": "22.0"})
    await pipeline.process_message("RaceControlMessages", {"Messages": {"1": {"Message": "Green flag"}}})

    await _drain_background_tasks(pipeline)
    pipeline_module.persist_weather_snapshot.assert_awaited_once()
    pipeline_module.persist_race_control_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_weather_persist_receives_the_real_event_time_not_processing_time() -> None:
    """Real bug this guards against: weather_snapshots.ts must reflect when F1 actually
    sent the message (from the raw archive during replay/tail), not whenever this happened
    to be processed - otherwise every replayed/caught-up historical tick gets stamped with
    the moment of replay instead of its real time."""
    pipeline = LiveSessionPipeline(stream_id="test-9f")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})

    event_time = datetime(2026, 7, 25, 16, 31, 47)
    await pipeline.process_message("WeatherData", {"AirTemp": "22.0"}, event_time=event_time)
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_weather_snapshot.assert_awaited_once_with(9850, {"AirTemp": "22.0"}, ts=event_time)


@pytest.mark.asyncio
async def test_race_control_deletion_marks_lap_deleted_once_session_key_known() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9b")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})

    await pipeline.process_message(
        "RaceControlMessages",
        {"Messages": {"1": {"Message": "CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17"}}},
    )
    await _drain_background_tasks(pipeline)

    pipeline_module.mark_lap_deleted.assert_awaited_once_with(9850, 55, 3)


@pytest.mark.asyncio
async def test_race_control_deletion_dropped_when_session_key_not_yet_known() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9c")

    await pipeline.process_message(
        "RaceControlMessages",
        {"Messages": {"1": {"Message": "CAR 55 (SAI) TIME 1:23.576 DELETED - TRACK LIMITS AT TURN 4 LAP 3 16:02:17"}}},
    )
    await _drain_background_tasks(pipeline)

    pipeline_module.mark_lap_deleted.assert_not_awaited()


@pytest.mark.asyncio
async def test_qualifying_part_transition_persists_results_once_session_key_known() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9d")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1"}}})
    await pipeline.process_message("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})

    await pipeline.process_message("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_qualifying_results.assert_awaited_once()
    args = pipeline_module.persist_qualifying_results.call_args.args
    assert args[0] == 9850
    assert args[1] == 1275
    assert args[2][0].qualifying_part == "Q1"


@pytest.mark.asyncio
async def test_qualifying_part_transition_does_not_persist_when_session_key_not_yet_known() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9e")
    await pipeline.process_message("TimingData", {"Lines": {"1": {"Position": "1"}}})
    await pipeline.process_message("SessionData", {"Series": {"1": {"QualifyingPart": 1}}})

    await pipeline.process_message("SessionData", {"Series": {"2": {"QualifyingPart": 2}}})
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_qualifying_results.assert_not_awaited()


# ---- SessionInfo-triggered driver roster / session metadata fetch ----

@pytest.mark.asyncio
async def test_session_info_fetches_persists_and_broadcasts_driver_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=_SAMPLE_SESSION_META))
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", AsyncMock(return_value=[_SAMPLE_DRIVER]))

    pipeline = LiveSessionPipeline(stream_id="test-roster-1")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain initial snapshot

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain the SessionInfo broadcast itself
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_session_metadata.assert_awaited_once_with(_SAMPLE_SESSION_META)
    pipeline_module.persist_driver_roster.assert_awaited_once()
    assert pipeline_module.persist_driver_roster.call_args.args[0] == 9850

    assert pipeline.state.driver_roster[1]["full_name"] == "Max Verstappen"

    message = queue.get_nowait()
    assert message["event"] == "driver_roster"
    assert message["data"]["driver_roster"]["1"]["name_acronym"] == "VER"
    assert message["data"]["driver_roster"]["1"]["team_colour"] == "3671C6"


@pytest.mark.asyncio
async def test_session_info_broadcasts_and_persists_resolved_total_laps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=_SAMPLE_SESSION_META))
    monkeypatch.setattr(pipeline_module, "fetch_total_laps", AsyncMock(return_value=57))

    pipeline = LiveSessionPipeline(stream_id="test-total-laps-1")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain initial snapshot

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain the SessionInfo broadcast itself
    await _drain_background_tasks(pipeline)

    assert pipeline.state.lap_count["TotalLaps"] == 57
    pipeline_module.persist_total_laps.assert_awaited_once_with(9850, 57)

    message = queue.get_nowait()
    assert message["event"] == "LapCount"
    assert message["data"]["lap_count"]["TotalLaps"] == 57


@pytest.mark.asyncio
async def test_no_lap_count_broadcast_when_openf1_has_no_laps_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Correct behavior for a genuinely live/future session - no fabricated total, no extra broadcast."""
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=_SAMPLE_SESSION_META))
    monkeypatch.setattr(pipeline_module, "fetch_total_laps", AsyncMock(return_value=None))

    pipeline = LiveSessionPipeline(stream_id="test-total-laps-2")
    _, queue = pipeline.subscribe()
    queue.get_nowait()

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain the SessionInfo broadcast itself
    await _drain_background_tasks(pipeline)

    assert "TotalLaps" not in pipeline.state.lap_count
    pipeline_module.persist_total_laps.assert_not_awaited()
    assert queue.empty()


@pytest.mark.asyncio
async def test_total_laps_not_persisted_when_session_metadata_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """persist_total_laps would UPDATE a `sessions` row that was never inserted - must be skipped,
    not fired anyway, when OpenF1 has no session metadata (so persist_session_metadata never ran)."""
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline_module, "fetch_total_laps", AsyncMock(return_value=57))

    pipeline = LiveSessionPipeline(stream_id="test-total-laps-3")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_session_metadata.assert_not_awaited()
    pipeline_module.persist_total_laps.assert_not_awaited()
    # The in-memory/broadcast side still resolves independently of session-metadata persistence.
    assert pipeline.state.lap_count["TotalLaps"] == 57


@pytest.mark.asyncio
async def test_confirmed_roster_path_also_resolves_total_laps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=_SAMPLE_SESSION_META))
    monkeypatch.setattr(pipeline_module, "fetch_total_laps", AsyncMock(return_value=57))

    pipeline = LiveSessionPipeline(stream_id="test-total-laps-4", confirmed_roster=_SAMPLE_CONFIRMED_ROSTER)
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    await _drain_background_tasks(pipeline)

    assert pipeline.state.lap_count["TotalLaps"] == 57
    pipeline_module.persist_total_laps.assert_awaited_once_with(9850, 57)


@pytest.mark.asyncio
async def test_driver_roster_fetch_only_triggered_once_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_roster = AsyncMock(return_value=[_SAMPLE_DRIVER])
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", fetch_roster)

    pipeline = LiveSessionPipeline(stream_id="test-roster-2")
    await pipeline.process_message("SessionInfo", {"Key": 9850})
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    await _drain_background_tasks(pipeline)

    fetch_roster.assert_awaited_once()


@pytest.mark.asyncio
async def test_driver_roster_fetch_not_triggered_when_session_key_still_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_roster = AsyncMock(return_value=[_SAMPLE_DRIVER])
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", fetch_roster)

    pipeline = LiveSessionPipeline(stream_id="test-roster-3")
    # A SessionInfo payload with no "Key" leaves state.session_key as None.
    await pipeline.process_message("SessionInfo", {"Meeting": {"Key": 1275}})
    await _drain_background_tasks(pipeline)

    fetch_roster.assert_not_awaited()


@pytest.mark.asyncio
async def test_driver_roster_broadcast_skipped_when_openf1_returns_no_drivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", AsyncMock(return_value=[]))

    pipeline = LiveSessionPipeline(stream_id="test-roster-4")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain initial snapshot

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain the SessionInfo broadcast itself
    await _drain_background_tasks(pipeline)

    pipeline_module.persist_driver_roster.assert_not_awaited()
    assert queue.empty()  # no driver_roster event broadcast
    assert pipeline.state.driver_roster == {}


# ---- confirmed_roster (pre-race lineup confirmation) ----

def test_confirmed_roster_is_set_immediately_on_construction() -> None:
    """No need to wait on SessionInfo/OpenF1 - the caller already told us who's driving."""
    pipeline = LiveSessionPipeline(stream_id="test-confirmed-1", confirmed_roster=_SAMPLE_CONFIRMED_ROSTER)

    assert pipeline.state.driver_roster[1]["full_name"] == "Lando Norris"
    assert pipeline.state.driver_roster[1]["name_acronym"] == "NOR"
    assert pipeline.state.driver_roster[1]["team_colour"] == "#F58020"
    assert pipeline.state.driver_roster[81]["full_name"] == "Pato O'Ward"


def test_subscribe_snapshot_includes_confirmed_roster_before_any_message_processed() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-confirmed-2", confirmed_roster=_SAMPLE_CONFIRMED_ROSTER)
    _, queue = pipeline.subscribe()
    message = queue.get_nowait()
    assert message["data"]["driver_roster"][1]["name_acronym"] == "NOR"


@pytest.mark.asyncio
async def test_session_info_persists_confirmed_roster_and_skips_openf1_driver_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_roster = AsyncMock(return_value=[_SAMPLE_DRIVER])
    monkeypatch.setattr(pipeline_module, "fetch_driver_roster", fetch_roster)
    monkeypatch.setattr(pipeline_module, "fetch_session_metadata", AsyncMock(return_value=_SAMPLE_SESSION_META))

    pipeline = LiveSessionPipeline(stream_id="test-confirmed-3", confirmed_roster=_SAMPLE_CONFIRMED_ROSTER)
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    await _drain_background_tasks(pipeline)

    # Session metadata (circuit/date/etc.) is still fetched from OpenF1 - only the roster is skipped.
    pipeline_module.persist_session_metadata.assert_awaited_once_with(_SAMPLE_SESSION_META)
    fetch_roster.assert_not_awaited()
    pipeline_module.persist_driver_roster.assert_not_awaited()

    pipeline_module.persist_confirmed_driver_roster.assert_awaited_once_with(9850, _SAMPLE_CONFIRMED_ROSTER)
    # The confirmed roster (set at construction) is untouched by the OpenF1-fetch path.
    assert pipeline.state.driver_roster[1]["full_name"] == "Lando Norris"


@pytest.mark.asyncio
async def test_session_info_does_not_rebroadcast_driver_roster_when_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The confirmed roster is already in the first snapshot every subscriber gets (from __init__) -
    no separate "driver_roster" event is needed/sent once SessionInfo arrives."""
    pipeline = LiveSessionPipeline(stream_id="test-confirmed-4", confirmed_roster=_SAMPLE_CONFIRMED_ROSTER)
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain initial snapshot

    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})
    queue.get_nowait()  # drain the SessionInfo broadcast itself
    await _drain_background_tasks(pipeline)

    assert queue.empty()


def test_no_confirmed_roster_falls_back_to_default_empty_state() -> None:
    """Backward compatibility: omitting confirmed_roster (curl calls, existing tests) behaves exactly
    as before - state.driver_roster starts empty and the OpenF1-fetch path is used."""
    pipeline = LiveSessionPipeline(stream_id="test-confirmed-5")
    assert pipeline.state.driver_roster == {}
    assert pipeline._confirmed_roster is None


def test_close_closes_archive_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "test.jsonl"
    pipeline = LiveSessionPipeline(stream_id="test-10", archive_path=archive_path)
    assert pipeline._archive_file is not None
    pipeline.close()
    assert pipeline._archive_file is None
    assert archive_path.exists()


def test_log_event_writes_non_message_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "test.jsonl"
    pipeline = LiveSessionPipeline(stream_id="test-11", archive_path=archive_path)
    pipeline.log_event("connection", {"status": "connected"})
    pipeline.close()

    content = archive_path.read_text()
    assert '"event_type": "connection"' in content
    assert '"status": "connected"' in content


# ---- Battle Radar wire shape ----

async def _advance_lap_with_gap(pipeline: LiveSessionPipeline, driver_number: int, lap_number: int, gap: str) -> None:
    await pipeline.process_message(
        "TimingData",
        {"Lines": {str(driver_number): {"NumberOfLaps": lap_number, "Position": "2", "IntervalToPositionAhead": {"Value": gap}}}},
    )


@pytest.mark.asyncio
async def test_battle_radar_alert_included_in_timing_data_wire_when_it_fires() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-battle-radar-1")
    _, queue = pipeline.subscribe()
    queue.get_nowait()  # drain snapshot

    await _advance_lap_with_gap(pipeline, 44, 1, "+2.500")
    queue.get_nowait()  # first message - one live gap sample recorded, not enough for a trend yet
    await _advance_lap_with_gap(pipeline, 44, 2, "+1.800")
    queue.get_nowait()  # two samples, decreasing - already "upcoming" tier, not asserted here
    await _advance_lap_with_gap(pipeline, 44, 3, "+1.100")  # three samples, still closing - fires "battle" tier

    message = queue.get_nowait()
    assert message["data"]["battle_radar"]["44"]["alert_level"] == "battle"
    assert message["data"]["battle_radar"]["44"]["gap_seconds"] == pytest.approx(1.1)


@pytest.mark.asyncio
async def test_battle_radar_wire_carries_null_once_alert_clears() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-battle-radar-2")
    _, queue = pipeline.subscribe()
    queue.get_nowait()

    await _advance_lap_with_gap(pipeline, 44, 1, "+2.500")
    queue.get_nowait()
    await _advance_lap_with_gap(pipeline, 44, 2, "+1.800")
    queue.get_nowait()
    await _advance_lap_with_gap(pipeline, 44, 3, "+1.100")
    queue.get_nowait()  # alert now active

    await _advance_lap_with_gap(pipeline, 44, 4, "+1.900")  # widened again - alert clears
    message = queue.get_nowait()
    assert message["data"]["battle_radar"]["44"] is None


@pytest.mark.asyncio
async def test_no_battle_radar_key_in_wire_when_no_lap_boundary_crossed() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-battle-radar-3")
    _, queue = pipeline.subscribe()
    queue.get_nowait()

    # A TimingData message with no NumberOfLaps never touches battle radar at all.
    await pipeline.process_message("TimingData", {"Lines": {"44": {"LastLapTime": {"Value": "1:27.150"}}}})
    message = queue.get_nowait()
    assert "battle_radar" not in message["data"]


# ---- diff_to_wire: new_radio_captures carries qualifying_part through to the client ----

def test_diff_to_wire_radio_capture_carries_qualifying_part_for_qualifying() -> None:
    state = SessionState()
    diff = StateDiff(
        event_name="TeamRadio",
        new_radio_captures=[
            RadioCapture(
                driver_number=1,
                utc=datetime(2025, 11, 30, 16, 10, 50),
                path="TeamRadio/x.mp3",
                lap_number=8,
                qualifying_part="Q2",
            )
        ],
    )
    wire = diff_to_wire(diff, state)
    assert wire["new_radio_captures"][0]["qualifying_part"] == "Q2"
    assert wire["new_radio_captures"][0]["lap_number"] == 8


def test_diff_to_wire_radio_capture_qualifying_part_is_none_for_a_race() -> None:
    """A race capture must never carry a stale/guessed qualifying segment - see
    SessionState._apply_team_radio, which only ever sets qualifying_part from
    self.qualifying_part (None outside qualifying)."""
    state = SessionState()
    diff = StateDiff(
        event_name="TeamRadio",
        new_radio_captures=[
            RadioCapture(
                driver_number=1,
                utc=datetime(2025, 11, 30, 16, 10, 50),
                path="TeamRadio/x.mp3",
                lap_number=8,
                qualifying_part=None,
            )
        ],
    )
    wire = diff_to_wire(diff, state)
    assert wire["new_radio_captures"][0]["qualifying_part"] is None
    assert wire["new_radio_captures"][0]["lap_number"] == 8
