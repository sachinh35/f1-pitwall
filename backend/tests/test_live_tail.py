"""Unit tests for utils/live_tail.py - the backend's tail-and-catch-up side of the
capture/backend split (see utils/raw_capture.py's RawStreamArchiver for the write side)."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from utils import live_tail
from utils.live_session_pipeline import get_pipeline


def _append_entry(log_path: Path, entry: dict) -> None:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _message_entry(event_name: str, payload: dict, timestamp: str = "t") -> dict:
    return {"timestamp": timestamp, "event_type": "message", "data": {"event_name": event_name, "payload": payload}}


@pytest.mark.asyncio
async def test_tail_log_file_catches_up_on_existing_messages_then_returns_when_stopped(tmp_path: Path) -> None:
    log_path = tmp_path / "live_test.jsonl"
    _append_entry(log_path, _message_entry("LapCount", {"CurrentLap": 1}))
    _append_entry(log_path, {"timestamp": "t", "event_type": "connection", "data": {"status": "connected"}})
    _append_entry(log_path, _message_entry("LapCount", {"CurrentLap": 2}))

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()

    stop_event = asyncio.Event()
    stop_event.set()  # already stopped -> catch-up runs once, then the follow loop exits immediately

    await live_tail.tail_log_file(log_path, pipeline, stop_event=stop_event)

    assert pipeline.process_message.await_args_list == [
        (("LapCount", {"CurrentLap": 1}), {"event_time": None}),
        (("LapCount", {"CurrentLap": 2}), {"event_time": None}),
    ]


@pytest.mark.asyncio
async def test_tail_log_file_passes_through_the_archived_event_time(tmp_path: Path) -> None:
    """Real bug this guards against: the archived capture timestamp (when F1 actually sent
    this message) must reach the pipeline, not get silently dropped - a persist path like
    weather_snapshots.ts needs it, or every replayed/caught-up historical message ends up
    stamped with the moment of replay instead of its real event time."""
    log_path = tmp_path / "live_test.jsonl"
    _append_entry(log_path, _message_entry("WeatherData", {"AirTemp": "25.1"}, timestamp="2026-07-25T16:31:47.399383"))

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()
    stop_event = asyncio.Event()
    stop_event.set()

    await live_tail.tail_log_file(log_path, pipeline, stop_event=stop_event)

    pipeline.process_message.assert_awaited_once_with(
        "WeatherData", {"AirTemp": "25.1"}, event_time=datetime(2026, 7, 25, 16, 31, 47, 399383)
    )


@pytest.mark.asyncio
async def test_tail_log_file_picks_up_lines_appended_after_catch_up(tmp_path: Path) -> None:
    log_path = tmp_path / "live_test.jsonl"
    _append_entry(log_path, _message_entry("LapCount", {"CurrentLap": 1}))

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()
    stop_event = asyncio.Event()

    task = asyncio.ensure_future(
        live_tail.tail_log_file(log_path, pipeline, poll_interval=0.05, stop_event=stop_event)
    )
    await asyncio.sleep(0.1)  # let it catch up and enter the follow loop

    _append_entry(log_path, _message_entry("LapCount", {"CurrentLap": 2}))
    await asyncio.sleep(0.2)  # give it at least one more poll cycle

    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert pipeline.process_message.await_args_list == [
        (("LapCount", {"CurrentLap": 1}), {"event_time": None}),
        (("LapCount", {"CurrentLap": 2}), {"event_time": None}),
    ]


@pytest.mark.asyncio
async def test_tail_log_file_ignores_a_partial_trailing_line_until_completed(tmp_path: Path) -> None:
    """A reader mid-write leaves a partial JSON line - must not be parsed as-is, and must
    still be picked up once the writer finishes it."""
    log_path = tmp_path / "live_test.jsonl"
    complete_entry = json.dumps(_message_entry("LapCount", {"CurrentLap": 1}))
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(complete_entry + "\n")
        f.write('{"event_type": "message", "data": {"event_name": "LapCount"')  # no trailing newline

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()
    stop_event = asyncio.Event()

    task = asyncio.ensure_future(
        live_tail.tail_log_file(log_path, pipeline, poll_interval=0.05, stop_event=stop_event)
    )
    await asyncio.sleep(0.1)

    assert pipeline.process_message.await_count == 1  # the partial line was not consumed

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(', "payload": {"CurrentLap": 2}}}\n')
    await asyncio.sleep(0.2)

    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert pipeline.process_message.await_args_list[-1].args == ("LapCount", {"CurrentLap": 2})


def test_start_tail_raises_file_not_found_for_a_missing_log(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        live_tail.start_tail(tmp_path / "live_does_not_exist.jsonl")


@pytest.mark.asyncio
async def test_start_tail_derives_a_stable_stream_id_and_registers_the_pipeline(tmp_path: Path) -> None:
    log_path = tmp_path / "live_quali_2026.jsonl"
    log_path.write_text("")

    stream_id = live_tail.start_tail(log_path, poll_interval=0.05)
    try:
        assert stream_id == "live_quali_2026"
        assert get_pipeline(stream_id) is not None
    finally:
        live_tail.stop_tail(stream_id)
        await asyncio.sleep(0.2)  # let the background task's finally-block unregister run


@pytest.mark.asyncio
async def test_start_tail_honors_an_explicit_stream_id(tmp_path: Path) -> None:
    log_path = tmp_path / "live_quali_2026.jsonl"
    log_path.write_text("")

    stream_id = live_tail.start_tail(log_path, stream_id="custom_id", poll_interval=0.05)
    try:
        assert stream_id == "custom_id"
        assert get_pipeline("custom_id") is not None
    finally:
        live_tail.stop_tail(stream_id)
        await asyncio.sleep(0.2)


def test_stop_tail_returns_false_for_an_unknown_stream_id() -> None:
    assert live_tail.stop_tail("not_a_real_stream") is False
