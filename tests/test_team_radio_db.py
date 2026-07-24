"""
Unit tests for utils/team_radio_db.py - previously only exercised indirectly
through mocked calls in test_team_radio_pipeline.py. This tests the actual
SQL-building logic directly, in particular the dynamic `_update` helper that
builds an UPDATE statement from arbitrary kwargs.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils import team_radio_db
from utils.team_radio_db import RadioClipStatus


def _mock_db(monkeypatch: pytest.MonkeyPatch, fetchval_result=None, fetch_result=None):
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=fetchval_result)
    mock_conn.fetch = AsyncMock(return_value=fetch_result or [])

    class _FakeConnCtx:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(team_radio_db.DatabaseManager, "get_connection", MagicMock(return_value=_FakeConnCtx()))
    return mock_conn


@pytest.mark.asyncio
async def test_insert_pending_returns_new_row_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch, fetchval_result=42)
    row_id = await team_radio_db.insert_pending(9850, 1, 12, datetime(2025, 11, 30, 16, 10, 50))
    assert row_id == 42
    args = mock_conn.fetchval.call_args.args
    assert args[1:] == (9850, 1, 12, datetime(2025, 11, 30, 16, 10, 50), RadioClipStatus.PENDING.value)


@pytest.mark.asyncio
async def test_mark_downloaded_updates_status_and_audio_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    await team_radio_db.mark_downloaded(7, "9850/clip.mp3")

    query = mock_conn.execute.call_args.args[0]
    params = mock_conn.execute.call_args.args[1:]
    assert "status = $2" in query
    assert "audio_path = $3" in query
    assert params == (7, RadioClipStatus.DOWNLOADED.value, "9850/clip.mp3")


@pytest.mark.asyncio
async def test_mark_failed_download_sets_status_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    await team_radio_db.mark_failed_download(7, "connection refused")

    params = mock_conn.execute.call_args.args[1:]
    assert params == (7, RadioClipStatus.FAILED_DOWNLOAD.value, "connection refused")


@pytest.mark.asyncio
async def test_mark_done_sets_transcript_and_transcribed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    await team_radio_db.mark_done(7, "box box confirm the tyre change")

    params = mock_conn.execute.call_args.args[1:]
    assert params[0] == 7
    assert params[1] == RadioClipStatus.DONE.value
    assert params[2] == "box box confirm the tyre change"
    assert isinstance(params[3], datetime)


@pytest.mark.asyncio
async def test_update_with_no_fields_does_not_touch_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_conn = _mock_db(monkeypatch)
    await team_radio_db._update(7)
    mock_conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_for_session_maps_rows_to_dataclasses(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rows = [
        {
            "id": 1, "session_key": 9850, "driver_number": 1, "lap_number": 12,
            "ts": datetime(2025, 11, 30, 16, 10, 50), "audio_path": "9850/x.mp3",
            "transcript": "box box", "status": "done", "error": None,
            "transcribed_at": datetime(2025, 11, 30, 16, 10, 55),
        }
    ]
    _mock_db(monkeypatch, fetch_result=fake_rows)
    clips = await team_radio_db.get_for_session(9850)
    assert len(clips) == 1
    assert clips[0].driver_number == 1
    assert clips[0].status == RadioClipStatus.DONE
    assert clips[0].transcript == "box box"
