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
from utils.radio_analysis import RadioMessageAnalysis
from utils.session_state import RadioCapture


def _make_capture() -> RadioCapture:
    return RadioCapture(
        driver_number=1,
        utc=datetime(2025, 11, 30, 16, 10, 50),
        path="TeamRadio/MAXVER01_1_20251130_191032.mp3",
        lap_number=12,
    )


def test_resolve_audio_url_without_session_path_falls_back_to_flat_url() -> None:
    """Only used when a capture arrives before SessionInfo has ever been seen - real F1 CDN
    404/403s a URL built this way (confirmed directly - see the session_path-aware test below),
    so this is a "best effort, will fail" fallback, not the expected happy path."""
    url = team_radio_pipeline.resolve_audio_url("TeamRadio/MAXVER01_1_20251130_191032.mp3")
    assert url == "https://livetiming.formula1.com/static/TeamRadio/MAXVER01_1_20251130_191032.mp3"


def test_resolve_audio_url_with_session_path_builds_the_real_working_url() -> None:
    """This exact URL shape was confirmed with a real 200/valid-MPEG-audio fetch against F1's
    live CDN (unauthenticated) - the session_path (from SessionInfo.Path) is what makes it work."""
    url = team_radio_pipeline.resolve_audio_url(
        "TeamRadio/MAXVER01_1_20251130_191032.mp3",
        session_path="2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/",
    )
    assert url == (
        "https://livetiming.formula1.com/static/2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/"
        "TeamRadio/MAXVER01_1_20251130_191032.mp3"
    )


def test_resolve_audio_url_handles_session_path_without_trailing_slash() -> None:
    url = team_radio_pipeline.resolve_audio_url(
        "TeamRadio/x.mp3", session_path="2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race"
    )
    assert url == "https://livetiming.formula1.com/static/2025/2025-11-30_Qatar_Grand_Prix/2025-11-30_Race/TeamRadio/x.mp3"


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

    async def fake_analyze_transcript(driver_label: str, lap_number, transcript: str) -> RadioMessageAnalysis:
        calls.append("analyze_transcript")
        assert driver_label == "Driver #1"
        assert lap_number == 12
        return RadioMessageAnalysis(
            speaker_role="pit_wall", reasoning="Box call.", is_notable=True, notable_reason="Pit stop called."
        )

    async def fake_mark_analyzed(row_id: int, speaker_role: str, is_notable: bool, notable_reason) -> None:
        calls.append("mark_analyzed")
        assert (speaker_role, is_notable, notable_reason) == ("pit_wall", True, "Pit stop called.")

    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "insert_pending", fake_insert_pending)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloading", fake_mark_downloading)
    monkeypatch.setattr(team_radio_pipeline, "download_binary", fake_download_binary)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloaded", fake_mark_downloaded)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_transcribing", fake_mark_transcribing)
    monkeypatch.setattr(team_radio_pipeline.whisper_transcriber, "transcribe", fake_transcribe)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_done", fake_mark_done)
    monkeypatch.setattr(team_radio_pipeline.radio_analysis, "analyze_transcript", fake_analyze_transcript)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_analyzed", fake_mark_analyzed)

    on_downloaded = AsyncMock()
    on_transcribed = AsyncMock()
    on_analyzed = AsyncMock()

    await team_radio_pipeline.process_radio_capture(
        session_key=9850,
        capture=_make_capture(),
        on_downloaded=on_downloaded,
        on_transcribed=on_transcribed,
        on_analyzed=on_analyzed,
    )

    assert calls == [
        "insert_pending", "mark_downloading", "download_binary", "mark_downloaded",
        "mark_transcribing", "transcribe", "mark_done", "analyze_transcript", "mark_analyzed",
    ]
    on_downloaded.assert_awaited_once_with("RADIO_CLIP_READY", 42)
    on_transcribed.assert_awaited_once_with("RADIO_TRANSCRIPT_READY", 42)
    on_analyzed.assert_awaited_once_with("RADIO_ANALYSIS_READY", 42)


@pytest.mark.asyncio
async def test_analysis_failure_never_regresses_an_already_successful_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transcript itself is already saved (mark_done) before analysis runs - a Gemini
    failure (quota, network, bad model id) must be swallowed, not raised, and must never
    touch mark_analyzed or the on_analyzed callback."""
    async def fake_insert_pending(**kwargs) -> int:
        return 55

    async def fake_analyze_transcript(driver_label: str, lap_number, transcript: str) -> RadioMessageAnalysis:
        raise RuntimeError("Gemini quota exceeded")

    mark_analyzed = AsyncMock()
    on_analyzed = AsyncMock()

    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "insert_pending", fake_insert_pending)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloading", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline, "download_binary", AsyncMock(return_value=Path("x.mp3")))
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_downloaded", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_transcribing", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline.whisper_transcriber, "transcribe", AsyncMock(return_value="box box"))
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_done", AsyncMock())
    monkeypatch.setattr(team_radio_pipeline.radio_analysis, "analyze_transcript", fake_analyze_transcript)
    monkeypatch.setattr(team_radio_pipeline.team_radio_db, "mark_analyzed", mark_analyzed)

    # Must not raise.
    await team_radio_pipeline.process_radio_capture(
        session_key=9850, capture=_make_capture(), on_analyzed=on_analyzed,
    )

    team_radio_pipeline.team_radio_db.mark_done.assert_awaited_once()
    mark_analyzed.assert_not_awaited()
    on_analyzed.assert_not_awaited()


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
