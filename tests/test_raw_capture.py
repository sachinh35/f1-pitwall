"""Unit tests for utils/raw_capture.py's RawStreamArchiver."""
import json
from pathlib import Path

import pytest

from utils.raw_capture import RawStreamArchiver


@pytest.mark.asyncio
async def test_handle_message_writes_flushed_message_entry(tmp_path: Path) -> None:
    log_path = tmp_path / "live_test_session.jsonl"
    archiver = RawStreamArchiver(log_path)

    await archiver.handle_message("LapCount", {"CurrentLap": 3})
    archiver.close()

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event_type"] == "message"
    assert entry["data"] == {"event_name": "LapCount", "payload": {"CurrentLap": 3}}
    assert "timestamp" in entry


def test_log_event_writes_flushed_non_message_entry(tmp_path: Path) -> None:
    log_path = tmp_path / "live_test_session.jsonl"
    archiver = RawStreamArchiver(log_path)

    archiver.log_event("connection", {"status": "connected"})
    archiver.close()

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert entry["event_type"] == "connection"
    assert entry["data"] == {"status": "connected"}


@pytest.mark.asyncio
async def test_every_write_is_flushed_before_close(tmp_path: Path) -> None:
    """The whole point of this sink is durability - a reader must be able to see each
    message immediately, without waiting for close()/a batch threshold (unlike
    LiveSessionPipeline's flush-every-50 archive)."""
    log_path = tmp_path / "live_test_session.jsonl"
    archiver = RawStreamArchiver(log_path)

    await archiver.handle_message("WeatherData", {"AirTemp": "25"})

    # Read independently, without closing the archiver's own handle first.
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1

    archiver.close()


def test_creates_parent_directory_if_missing(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "live_test_session.jsonl"
    archiver = RawStreamArchiver(log_path)
    archiver.close()
    assert log_path.parent.is_dir()


@pytest.mark.asyncio
async def test_appends_to_an_existing_file_rather_than_truncating(tmp_path: Path) -> None:
    """Restarting the capture process (e.g. the watchdog after a crash) must resume the
    same file, not lose what was already captured."""
    log_path = tmp_path / "live_test_session.jsonl"
    first = RawStreamArchiver(log_path)
    await first.handle_message("LapCount", {"CurrentLap": 1})
    first.close()

    second = RawStreamArchiver(log_path)
    await second.handle_message("LapCount", {"CurrentLap": 2})
    second.close()

    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["data"]["payload"] == {"CurrentLap": 1}
    assert json.loads(lines[1])["data"]["payload"] == {"CurrentLap": 2}


def test_close_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "live_test_session.jsonl"
    archiver = RawStreamArchiver(log_path)
    archiver.close()
    archiver.close()  # must not raise
