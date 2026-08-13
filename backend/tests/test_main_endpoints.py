"""
Endpoint-level unit tests for main.py's remaining (previously untested) routes.

Follows the pattern established in tests/test_main.py: TestClient without entering it
as a context manager (so the startup event - which needs a real Postgres pool - never
fires), and each downstream utils module mocked at the `main.<module>` level.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from utils.lap_comparison import Corner, DeltaTrace, LapTrace

client = TestClient(main.app)


# ---- GET /years, /session-types (no dependencies) ----

def test_get_years() -> None:
    response = client.get("/years")
    assert response.status_code == 200
    assert response.json()["years_list"] == [2023, 2024, 2025]


def test_get_session_types() -> None:
    response = client.get("/session-types")
    assert response.status_code == 200
    assert response.json()["session_types"] == ["Qualifying", "Race"]


# ---- GET /races/{year} ----

def test_get_races_for_year_success() -> None:
    fake_race = {"session_key": 1, "location": "Doha", "session_name": "Race", "country_code": "QAT"}
    with patch.object(main.race_session, "get_races_by_year", new=AsyncMock(return_value=[fake_race])):
        response = client.get("/races/2025")
    assert response.status_code == 200
    assert response.json()["all_races"] == [fake_race]


def test_get_races_for_year_failure_returns_500() -> None:
    with patch.object(main.race_session, "get_races_by_year", new=AsyncMock(side_effect=RuntimeError("db down"))):
        response = client.get("/races/2025")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to fetch races"


# ---- GET /session-results/{session_key} ----

def test_get_session_results_success() -> None:
    with patch.object(main.race_session, "get_results_by_session_key", new=AsyncMock(return_value=[])):
        response = client.get("/session-results/123")
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_get_session_results_propagates_exception() -> None:
    """The handler does `raise e` (not HTTPException) on failure - it relies on FastAPI's
    default unhandled-exception -> 500 behavior rather than converting it itself, so
    TestClient (which re-raises server exceptions by default) sees the raw exception."""
    with patch.object(
        main.race_session, "get_results_by_session_key", new=AsyncMock(side_effect=ValueError("bad session"))
    ):
        with pytest.raises(ValueError, match="bad session"):
            client.get("/session-results/123")


# ---- POST /session-lap-data/{session_key} ----

def test_get_session_lap_data_rejects_empty_driver_numbers() -> None:
    # LapDataRequest's own `min_items=1` constraint rejects this at the pydantic
    # validation layer (422) before the handler's own empty-list check ever runs.
    response = client.post("/session-lap-data/123", json={"driver_numbers": []})
    assert response.status_code == 422


def test_get_session_lap_data_success() -> None:
    with patch.object(main.lap_data, "get_lap_data_for_session", new=AsyncMock(return_value=[])):
        response = client.post("/session-lap-data/123", json={"driver_numbers": [1, 44]})
    assert response.status_code == 200
    assert response.json() == {"session_key": 123, "lap_data": []}


def test_get_session_lap_data_failure_returns_500() -> None:
    with patch.object(
        main.lap_data, "get_lap_data_for_session", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        response = client.post("/session-lap-data/123", json={"driver_numbers": [1]})
    assert response.status_code == 500
    assert "Failed to fetch lap data" in response.json()["detail"]


# ---- GET /session-stints/{session_key} ----

def test_get_session_stints_success() -> None:
    with patch.object(main.stints, "get_stints_for_session", new=AsyncMock(return_value=[])):
        response = client.get("/session-stints/123")
    assert response.status_code == 200
    assert response.json() == {"session_key": 123, "stints": []}


def test_get_session_stints_failure_returns_500() -> None:
    with patch.object(main.stints, "get_stints_for_session", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.get("/session-stints/123")
    assert response.status_code == 500


# ---- GET /session-race-control-events/{session_key} ----

def test_get_session_race_control_events_success() -> None:
    with patch.object(main.race_control, "get_race_control_events_for_session", new=AsyncMock(return_value=[])):
        response = client.get("/session-race-control-events/123")
    assert response.status_code == 200
    assert response.json() == {"session_key": 123, "events": []}


def test_get_session_race_control_events_failure_returns_500() -> None:
    with patch.object(
        main.race_control, "get_race_control_events_for_session", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        response = client.get("/session-race-control-events/123")
    assert response.status_code == 500


# ---- POST /authenticate-f1tv ----

def test_authenticate_f1tv_success() -> None:
    with patch.object(
        main.f1_auth,
        "authenticate_f1tv",
        new=AsyncMock(return_value={"access_token": "tok123", "cookies": "c=1"}),
    ):
        response = client.post("/authenticate-f1tv", json={"email": "a@b.com", "password": "secret"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["access_token"] == "tok123"


def test_authenticate_f1tv_failure_returns_401() -> None:
    with patch.object(
        main.f1_auth, "authenticate_f1tv", new=AsyncMock(side_effect=RuntimeError("bad creds"))
    ):
        response = client.post("/authenticate-f1tv", json={"email": "a@b.com", "password": "wrong"})
    assert response.status_code == 401
    assert "F1 TV Pro authentication failed" in response.json()["detail"]


# ---- POST /authenticate-f1tv/browser-start, GET .../browser-status ----

def test_start_browser_auth_success() -> None:
    with patch.object(main.f1_auth, "start_browser_auth_flow", return_value="https://f1login.example/start"):
        response = client.post("/authenticate-f1tv/browser-start")
    assert response.status_code == 200
    assert response.json()["auth_url"] == "https://f1login.example/start"


def test_start_browser_auth_failure_returns_500() -> None:
    with patch.object(main.f1_auth, "start_browser_auth_flow", side_effect=RuntimeError("boom")):
        response = client.post("/authenticate-f1tv/browser-start")
    assert response.status_code == 500


def test_browser_auth_status() -> None:
    with patch.object(
        main.f1_auth, "check_browser_auth_status", return_value={"status": "pending", "auth_url": "https://x", "error": None}
    ):
        response = client.get("/authenticate-f1tv/browser-status")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


# ---- GET /team-driver-pool ----

def test_get_team_driver_pool_success() -> None:
    with patch.object(main, "get_team_driver_pool", new=AsyncMock(return_value=[])):
        response = client.get("/team-driver-pool?season_year=2026")
    assert response.status_code == 200
    assert response.json() == {"season_year": 2026, "drivers": []}


def test_get_team_driver_pool_failure_returns_500() -> None:
    with patch.object(main, "get_team_driver_pool", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.get("/team-driver-pool?season_year=2026")
    assert response.status_code == 500


# ---- POST /simulate-live-stream ----

def test_simulate_live_stream_success() -> None:
    with patch.object(main.replay, "start_replay", return_value="sim-abc123"):
        response = client.post("/simulate-live-stream", json={"log_file": "some_race.jsonl"})
    assert response.status_code == 200
    body = response.json()
    assert body["stream_id"] == "sim-abc123"
    assert body["log_file"] == str(Path("stream_logs") / "some_race.jsonl")


def test_simulate_live_stream_missing_file_returns_404() -> None:
    with patch.object(main.replay, "start_replay", side_effect=FileNotFoundError()):
        response = client.post("/simulate-live-stream", json={"log_file": "missing.jsonl"})
    assert response.status_code == 404


def test_simulate_live_stream_failure_returns_500() -> None:
    with patch.object(main.replay, "start_replay", side_effect=RuntimeError("boom")):
        response = client.post("/simulate-live-stream", json={"log_file": "some_race.jsonl"})
    assert response.status_code == 500


# ---- POST /attach-live-stream ----

def test_attach_live_stream_with_explicit_session_name() -> None:
    with patch.object(main.live_tail, "start_tail", return_value="live_quali_2026") as mock_start_tail, \
         patch("pathlib.Path.exists", return_value=True):
        response = client.post("/attach-live-stream", json={"session_name": "quali_2026"})
    assert response.status_code == 200
    assert response.json()["stream_id"] == "live_quali_2026"
    mock_start_tail.assert_called_once()


def test_attach_live_stream_without_session_name_uses_latest(tmp_path, monkeypatch) -> None:
    fake_log = tmp_path / "live_abc.jsonl"
    fake_log.write_text("{}")
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)
    with patch.object(main.live_tail, "start_tail", return_value="live_abc"):
        response = client.post("/attach-live-stream", json={})
    assert response.status_code == 200
    assert response.json()["stream_id"] == "live_abc"


def test_attach_live_stream_without_any_capture_returns_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)
    response = client.post("/attach-live-stream", json={})
    assert response.status_code == 404


def test_attach_live_stream_failure_returns_500() -> None:
    with patch.object(main.live_tail, "start_tail", side_effect=RuntimeError("boom")), \
         patch("pathlib.Path.exists", return_value=True):
        response = client.post("/attach-live-stream", json={"session_name": "quali_2026"})
    assert response.status_code == 500


# ---- GET /live-stream/current ----

def test_get_current_live_stream_found(tmp_path, monkeypatch) -> None:
    fake_log = tmp_path / "live_abc.jsonl"
    fake_log.write_text("{}")
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)
    response = client.get("/live-stream/current")
    assert response.status_code == 200
    body = response.json()
    assert body["session_name"] == "abc"
    assert body["stream_id"] == "live_abc"


def test_get_current_live_stream_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)
    response = client.get("/live-stream/current")
    assert response.status_code == 404


# ---- GET /live/{stream_id}/events ----

def test_stream_live_events_404_when_no_pipeline_and_no_reattach(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)
    with patch.object(main, "get_pipeline", return_value=None):
        response = client.get("/live/not-a-real-stream/events")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_live_events_reattaches_from_disk(tmp_path, monkeypatch) -> None:
    """Calls the route coroutine directly (bypassing the ASGI/httpx transport, which -
    being a genuinely never-ending SSE stream - has no clean "read one event then stop"
    signal on a synchronous TestClient) so the generator can be driven and torn down
    deterministically."""
    import asyncio

    fake_log = tmp_path / "live_abc.jsonl"
    fake_log.write_text("{}")
    monkeypatch.setattr(main, "STREAM_LOGS_DIR", tmp_path)

    queue: "asyncio.Queue" = asyncio.Queue()
    queue.put_nowait({"id": 1, "event": "snapshot", "data": {"hello": "world"}})
    unsubscribed = []
    fake_pipeline = type(
        "FakePipeline",
        (),
        {
            "subscribe": lambda self: ("sub-1", queue),
            "unsubscribe": lambda self, subscriber_id: unsubscribed.append(subscriber_id),
        },
    )()

    fake_request = type("FakeRequest", (), {"is_disconnected": staticmethod(lambda: _false())})()

    async def _false():
        return False

    with patch.object(main, "get_pipeline", side_effect=[None, fake_pipeline]), \
         patch.object(main.live_tail, "start_tail") as mock_start_tail:
        response = await main.stream_live_events("live_abc", fake_request)

    first_event = await anext(response.body_iterator)
    assert first_event["event"] == "snapshot"
    await response.body_iterator.aclose()

    mock_start_tail.assert_called_once_with(fake_log, stream_id="live_abc")
    assert unsubscribed == ["sub-1"]


# ---- GET /lap-comparison/{session_key} ----

def _fake_row(**kwargs):
    return type("Row", (), kwargs)()


def test_lap_comparison_success() -> None:
    row = _fake_row(dt_ms=[0, 100], x=[0, 1], y=[0, 1], speed=[200, 210], throttle_pct=[100, 100], brake_pct=[0, 0])
    trace = LapTrace(distance_m=[0, 10], time_ms=[0, 100], speed_kmh=[200, 210], throttle_pct=[100, 100], brake_pct=[0, 0], acceleration_ms2=[0, 1])
    delta = DeltaTrace(distance_m=[0, 10], delta_seconds=[0, 0.1], corners=[Corner(distance_m=5, apex_speed_kmh=150)])

    with patch.object(main.lap_telemetry_db, "get_lap_telemetry", new=AsyncMock(return_value=row)), \
         patch.object(main.lap_telemetry_db, "get_lap_position", new=AsyncMock(return_value=row)), \
         patch.object(main, "build_lap_trace", return_value=trace), \
         patch.object(main, "compute_delta_trace", return_value=delta):
        response = client.get("/lap-comparison/123?driver_a=1&lap_a=1&driver_b=2&lap_b=1")

    assert response.status_code == 200
    body = response.json()
    assert body["driver_a"]["driver_number"] == 1
    assert body["delta"]["corners"] == [{"distance_m": 5, "apex_speed_kmh": 150}]


def test_lap_comparison_missing_data_returns_404() -> None:
    with patch.object(main.lap_telemetry_db, "get_lap_telemetry", new=AsyncMock(return_value=None)), \
         patch.object(main.lap_telemetry_db, "get_lap_position", new=AsyncMock(return_value=None)):
        response = client.get("/lap-comparison/123?driver_a=1&lap_a=1&driver_b=2&lap_b=1")
    assert response.status_code == 404


def test_lap_comparison_failure_returns_500() -> None:
    with patch.object(main.lap_telemetry_db, "get_lap_telemetry", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.get("/lap-comparison/123?driver_a=1&lap_a=1&driver_b=2&lap_b=1")
    assert response.status_code == 500


# ---- GET /team-radio/{session_key} ----

def test_get_team_radio_success() -> None:
    with patch.object(main.team_radio_db, "get_for_session", new=AsyncMock(return_value=[])):
        response = client.get("/team-radio/123")
    assert response.status_code == 200
    assert response.json() == {"session_key": 123, "clips": []}


def test_get_team_radio_failure_returns_500() -> None:
    with patch.object(main.team_radio_db, "get_for_session", new=AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.get("/team-radio/123")
    assert response.status_code == 500


# ---- startup/shutdown lifecycle hooks ----

@pytest.mark.asyncio
async def test_startup_event_initializes_pool() -> None:
    with patch.object(main.DatabaseManager, "get_pool", new=AsyncMock()) as mock_get_pool:
        await main.startup_event()
    mock_get_pool.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_event_closes_pool() -> None:
    with patch.object(main.DatabaseManager, "close_pool", new=AsyncMock()) as mock_close_pool:
        await main.shutdown_event()
    mock_close_pool.assert_called_once()
