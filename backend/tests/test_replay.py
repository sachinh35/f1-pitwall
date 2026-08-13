"""Unit tests for utils/replay.py."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from utils.replay import iter_log_messages, replay_log_file


def _write_log(tmp_path: Path, entries: list[dict]) -> Path:
    log_path = tmp_path / "test_stream.jsonl"
    with open(log_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return log_path


def test_iter_log_messages_yields_only_message_events(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, [
        {"timestamp": "t1", "event_type": "connection", "data": {"status": "connected"}},
        {"timestamp": "t2", "event_type": "message", "data": {"event_name": "WeatherData", "payload": {"AirTemp": "25"}}},
        {"timestamp": "t3", "event_type": "message", "data": {"event_name": "LapCount", "payload": {"CurrentLap": 1}}},
    ])

    result = list(iter_log_messages(log_path))

    assert result == [
        ("t2", "WeatherData", {"AirTemp": "25"}),
        ("t3", "LapCount", {"CurrentLap": 1}),
    ]


def test_iter_log_messages_skips_malformed_and_empty_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "test_stream.jsonl"
    with open(log_path, "w") as f:
        f.write("not valid json\n")
        f.write("\n")
        f.write(json.dumps({"event_type": "message", "data": {"event_name": "LapCount", "payload": {"CurrentLap": 1}}}) + "\n")

    result = list(iter_log_messages(log_path))
    assert result == [("", "LapCount", {"CurrentLap": 1})]


def test_iter_log_messages_skips_messages_missing_event_name_or_payload(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, [
        {"event_type": "message", "data": {"event_name": None, "payload": {"x": 1}}},
        {"event_type": "message", "data": {"event_name": "WeatherData", "payload": None}},
        {"event_type": "message", "data": {"event_name": "LapCount", "payload": {"CurrentLap": 1}}},
    ])

    result = list(iter_log_messages(log_path))
    assert result == [("", "LapCount", {"CurrentLap": 1})]


@pytest.mark.asyncio
async def test_replay_log_file_processes_every_message_in_order(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, [
        {"timestamp": "2025-11-30T16:00:00.000000", "event_type": "message",
         "data": {"event_name": "LapCount", "payload": {"CurrentLap": 1}}},
        {"timestamp": "2025-11-30T16:00:00.010000", "event_type": "message",
         "data": {"event_name": "LapCount", "payload": {"CurrentLap": 2}}},
    ])

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()

    count = await replay_log_file(log_path, pipeline, speed_factor=1000.0)

    assert count == 2
    assert pipeline.process_message.await_args_list[0].args == ("LapCount", {"CurrentLap": 1})
    assert pipeline.process_message.await_args_list[1].args == ("LapCount", {"CurrentLap": 2})


@pytest.mark.asyncio
async def test_replay_log_file_caps_large_gaps(tmp_path: Path) -> None:
    # A huge real-time gap between messages (e.g. a stream reconnect) must not
    # stall replay for the full real duration - it should be capped.
    log_path = _write_log(tmp_path, [
        {"timestamp": "2025-11-30T16:00:00.000000", "event_type": "message",
         "data": {"event_name": "LapCount", "payload": {"CurrentLap": 1}}},
        {"timestamp": "2025-11-30T18:00:00.000000", "event_type": "message",  # 2 hours later
         "data": {"event_name": "LapCount", "payload": {"CurrentLap": 2}}},
    ])

    pipeline = type("FakePipeline", (), {})()
    pipeline.process_message = AsyncMock()

    import time
    start = time.monotonic()
    await replay_log_file(log_path, pipeline, speed_factor=1.0, max_gap_seconds=0.01)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # would be ~2 hours without the cap
