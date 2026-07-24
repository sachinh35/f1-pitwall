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

from utils import live_session_pipeline as pipeline_module
from utils.live_session_pipeline import LiveSessionPipeline


async def _drain_background_tasks(pipeline: LiveSessionPipeline) -> None:
    """Let any asyncio.create_task-spawned work (persist calls) finish before asserting on it."""
    if pipeline._background_tasks:
        await asyncio.gather(*list(pipeline._background_tasks))


@pytest.fixture(autouse=True)
def _mock_persistence(monkeypatch: pytest.MonkeyPatch):
    """Every test gets fresh, no-op mocks for everything process_message can spawn."""
    monkeypatch.setattr(pipeline_module, "persist_completed_lap", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_weather_snapshot", AsyncMock())
    monkeypatch.setattr(pipeline_module, "persist_race_control_entry", AsyncMock())
    monkeypatch.setattr(pipeline_module, "process_radio_capture", AsyncMock())


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
async def test_new_radio_capture_triggers_detached_download_pipeline() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-8")
    await pipeline.process_message("SessionInfo", {"Key": 9850})
    await pipeline.process_message(
        "TeamRadio", {"Captures": [{"Utc": "2025-01-01T00:00:00Z", "RacingNumber": "1", "Path": "TeamRadio/x.mp3"}]}
    )

    await _drain_background_tasks(pipeline)
    pipeline_module.process_radio_capture.assert_awaited_once()
    assert pipeline_module.process_radio_capture.call_args.kwargs["session_key"] == 9850


@pytest.mark.asyncio
async def test_weather_and_race_control_persist_immediately_not_on_lap_boundary() -> None:
    pipeline = LiveSessionPipeline(stream_id="test-9")
    await pipeline.process_message("SessionInfo", {"Key": 9850, "Meeting": {"Key": 1275}})

    await pipeline.process_message("WeatherData", {"AirTemp": "22.0"})
    await pipeline.process_message("RaceControlMessages", {"Messages": {"1": {"Message": "Green flag"}}})

    await _drain_background_tasks(pipeline)
    pipeline_module.persist_weather_snapshot.assert_awaited_once()
    pipeline_module.persist_race_control_entry.assert_awaited_once()


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
