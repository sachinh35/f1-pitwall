"""
Unit tests for utils/team_radio_pipeline.py's state-machine orchestration.

All external effects (DB, network download, Whisper transcription) are
mocked here - they're each already covered by their own tests/real smoke
tests (test_http_client.py, and a real end-to-end Whisper run against a
synthesized clip). This file's job is to verify the *sequencing* is correct:
right calls, right order, right status transitions, failures isolated and
never re-raised.
"""
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from utils import team_radio_pipeline
from utils.session_state import RadioCapture


def _make_capture() -> RadioCapture:
    return RadioCapture(
        driver_number=1,
        utc=datetime(2025, 11, 30, 16, 10, 50),
        path="TeamRadio/MAXVER01_1_20251130_191032.mp3",
        lap_number=12,
    )


def test_resolve_audio_url_builds_expected_url() -> None:
    url = team_radio_pipeline.resolve_audio_url("TeamRadio/MAXVER01_1_20251130_191032.mp3")
    assert url == "https://livetiming.formula1.com/static/TeamRadio/MAXVER01_1_20251130_191032.mp3"


def test_local_audio_path_uses_filename_and_session_key() -> None:
    capture = _make_capture()
    path = team_radio_pipeline.local_audio_path(9850, capture, cache_dir=Path("cache"))
    assert path == Path("cache/9850/MAXVER01_1_20251130_191032.mp3")


def test_web_relative_audio_path_excludes_cache_dir_name() -> None:
    # Must match what main.py's `/audio` static mount actually serves - the
    # mount root IS the cache dir, so the stored path must not repeat its name.
    capture = _make_capture()
    assert team_radio_pipeline.web_relative_audio_path(9850, capture) == "9850/MAXVER01_1_20251130_191032.mp3"


@pytest.mark.asyncio
async def test_happy_path_transitions_through_every_status_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_insert_pending(**kwargs) -> int:
        calls.append("insert_pending")
        return 42

    async def fake_mark_downloading(row_id: int) -> None:
        assert row_id == 42
        calls.append("mark_downloading")

    async def fake_download_binary(url: str, dest: Path, headers=None) -> Path:
        calls.append("download_binary")
        return dest

    async def fake_mark_downloaded(row_id: int, audio_path: str) -> None:
        calls.append("mark_downloaded")

    async def fake_mark_transcribing(row_id: int) -> None:
        calls.append("mark_transcribing")

    async def fake_transcribe(audio_path: Path) -> str:
        calls.append("transcribe")
        return "Box box, confirm the tyre change."

    async def fake_mark_done(row_id: int, transcript: str) -> None:
        assert transcript == "Box box, confirm the tyre change."
        calls.append("mark_done")

    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "insert_pending", fake_insert_pending)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloading", fake_mark_downloading)
    monkeypatch.setattr(team_radio_pipeline, "download_binary", fake_download_binary)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloaded", fake_mark_downloaded)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_transcribing", fake_mark_transcribing)
    monkeypatch.setattr(team_radio_pipeline.whisper_transcriber, "transcribe", fake_transcribe)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_done", fake_mark_done)

    on_downloaded = AsyncMock()
    on_transcribed = AsyncMock()

    await team_radio_pipeline.process_radio_capture(
        session_key=9850,
        capture=_make_capture(),
        on_downloaded=on_downloaded,
        on_transcribed=on_transcribed,
    )

    assert calls == [
        "insert_pending", "mark_downloading", "download_binary", "mark_downloaded",
        "mark_transcribing", "transcribe", "mark_done",
    ]
    on_downloaded.assert_awaited_once_with("RADIO_CLIP_READY", 42)
    on_transcribed.assert_awaited_once_with("RADIO_TRANSCRIPT_READY", 42)


@pytest.mark.asyncio
async def test_download_failure_marks_failed_and_never_attempts_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_insert_pending(**kwargs) -> int:
        return 7

    async def fake_download_binary(url: str, dest: Path, headers=None) -> Path:
        raise ConnectionError("no valid F1TV token")

    mark_failed_download = AsyncMock()
    mark_transcribing = AsyncMock()  # should never be called

    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "insert_pending", fake_insert_pending)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloading", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline, "download_binary", fake_download_binary)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_failed_download", mark_failed_download)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_transcribing", mark_transcribing)

    on_downloaded = AsyncMock()

    # Must not raise - a bad clip can never take down the caller.
    await team_radio_pipeline.process_radio_capture(
        session_key=9850, capture=_make_capture(), on_downloaded=on_downloaded,
    )

    mark_failed_download.assert_awaited_once()
    assert mark_failed_download.call_args.args[0] == 7
    assert "no valid F1TV token" in mark_failed_download.call_args.args[1]
    mark_transcribing.assert_not_awaited()
    on_downloaded.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcription_failure_marks_failed_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_insert_pending(**kwargs) -> int:
        return 9

    async def fake_transcribe(audio_path: Path) -> str:
        raise RuntimeError("model file not found")

    mark_failed_transcription = AsyncMock()
    mark_done = AsyncMock()  # should never be called

    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "insert_pending", fake_insert_pending)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloading", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline, "download_binary", AsyncMock(return_value=Path("x.mp3")))
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloaded", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_transcribing", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline.whisper_transcriber, "transcribe", fake_transcribe)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_failed_transcription", mark_failed_transcription)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_done", mark_done)

    await team_radio_pipeline.process_radio_capture(session_key=9850, capture=_make_capture())

    mark_failed_transcription.assert_awaited_once()
    assert mark_failed_transcription.call_args.args[0] == 9
    mark_done.assert_not_awaited()
