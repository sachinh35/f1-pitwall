import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from api_pydantic_models.lap_comparison import (
    CornerResponse,
    DeltaTraceResponse,
    LapComparisonResponse,
    LapTraceResponse,
)
from api_pydantic_models.lap_data import GetSessionLapDataResponse, LapDataRequest
from api_pydantic_models.live_stream import (
    AttachStreamRequest,
    AuthenticateRequest,
    AuthenticateResponse,
    BrowserAuthStatusResponse,
    CurrentLiveStreamResponse,
    GetTeamDriverPoolResponse,
    GetTeamRadioResponse,
    SimulateStreamRequest,
    StartBrowserAuthResponse,
    StartStreamRequest,
    StartStreamResponse,
    TokenStatusResponse,
    UpdateTokenRequest,
)
from api_pydantic_models.race_control import GetSessionRaceControlEventsResponse
from api_pydantic_models.race_sesssions import GetAllSessionTypesResponse, GetSessionResultsResponse, SessionType
from api_pydantic_models.races import GetAvailableYearsResponse, GetRacesForYearsResponse
from api_pydantic_models.stints import GetSessionStintsResponse
from utils import f1_auth, lap_data, lap_telemetry_db, live_stream, live_tail, race_control, race_session, replay, stints, team_radio_db
from utils.database import DatabaseManager
from utils.lap_comparison import build_lap_trace, compute_delta_trace
from utils.live_session_pipeline import get_pipeline
from utils.live_stream import STREAM_LOGS_DIR
from utils.team_driver_pool_db import get_team_driver_pool
from utils.team_radio_pipeline import AUDIO_CACHE_DIR

CURRENT_SEASON_YEAR: int = 2026

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """Initialize database connection pool on startup."""
    await DatabaseManager.get_pool()


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection pool on shutdown."""
    await DatabaseManager.close_pool()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change in production!
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_CACHE_DIR)), name="audio")


@app.get("/years")
def get_years() -> GetAvailableYearsResponse:
    return GetAvailableYearsResponse(years_list=list(range(2023, 2026)))


@app.get("/races/{year}")
async def get_races_for_year(year: int) -> GetRacesForYearsResponse:
    try:
        races = await race_session.get_races_by_year(year)
        return GetRacesForYearsResponse(all_races=races)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch races")


@app.get("/session-types")
def get_session_types() -> GetAllSessionTypesResponse:
    return GetAllSessionTypesResponse(session_types=[SessionType.QUALIFYING, SessionType.RACE])


@app.get("/session-results/{session_key}")
async def get_session_results(session_key: int) -> GetSessionResultsResponse:
    try:
        logging.info("Request: session results for session_key=%s", session_key)
        results = await race_session.get_results_by_session_key(session_key=session_key)
        logging.info("Response: returning %d session results for session_key=%s", len(results), session_key)
        return GetSessionResultsResponse(results=results)
    except Exception as e:
        logging.exception("Error in get_session_results for session_key=%s", session_key)
        raise e


@app.post("/session-lap-data/{session_key}")
async def get_session_lap_data(
    session_key: int,
    request: LapDataRequest
) -> GetSessionLapDataResponse:
    """
    Get lap data for a specific session and driver(s).

    - Checks PostgreSQL database first
    - If data not found, fetches from OpenF1 API, stores in DB, then returns
    - Returns data filtered by requested driver_numbers
    """
    try:
        if not request.driver_numbers:
            raise HTTPException(
                status_code=400,
                detail="driver_numbers list cannot be empty"
            )

        logging.info("Request: lap data for session_key=%s drivers=%s", session_key, request.driver_numbers)
        lap_data_list = await lap_data.get_lap_data_for_session(
            session_key=session_key,
            driver_numbers=request.driver_numbers
        )
        logging.info("Response: returning %d lap records for session_key=%s", len(lap_data_list), session_key)
        return GetSessionLapDataResponse(
            session_key=session_key,
            lap_data=lap_data_list
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error in get_session_lap_data for session_key=%s", session_key)
        raise HTTPException(status_code=500, detail=f"Failed to fetch lap data: {str(e)}")


@app.get("/session-stints/{session_key}")
async def get_session_stints(session_key: int) -> GetSessionStintsResponse:
    """
    Get stints for a specific session.
    - Checks DB first
    - If absent, fetches from OpenF1, stores, then returns
    """
    try:
        logging.info("Request: stints for session_key=%s", session_key)
        stint_list = await stints.get_stints_for_session(session_key)
        logging.info("Response: returning %d stints for session_key=%s", len(stint_list), session_key)
        return GetSessionStintsResponse(session_key=session_key, stints=stint_list)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error in get_session_stints for session_key=%s", session_key)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stints: {str(e)}")


@app.get("/session-race-control-events/{session_key}")
async def get_session_race_control_events(session_key: int) -> GetSessionRaceControlEventsResponse:
    """
    Get race control events for a specific session.
    - Checks DB first
    - If absent, fetches from OpenF1, stores, then returns
    """
    try:
        logging.info("Request: race control events for session_key=%s", session_key)
        event_list = await race_control.get_race_control_events_for_session(session_key)
        logging.info("Response: returning %d race control events for session_key=%s", len(event_list), session_key)
        return GetSessionRaceControlEventsResponse(session_key=session_key, events=event_list)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error in get_session_race_control_events for session_key=%s", session_key)
        raise HTTPException(status_code=500, detail=f"Failed to fetch race control events: {str(e)}")


@app.post("/authenticate-f1tv", response_model=AuthenticateResponse)
async def authenticate_f1tv(request: AuthenticateRequest) -> AuthenticateResponse:
    """
    Authenticate with F1 TV Pro using email and password.
    """
    try:
        logging.info("Request: F1 TV Pro authentication for email: %s", request.email)

        auth_result = await f1_auth.authenticate_f1tv(
            email=request.email,
            password=request.password
        )

        logging.info("Response: F1 TV Pro authentication successful")

        return AuthenticateResponse(
            success=True,
            access_token=auth_result["access_token"],
            cookies=auth_result.get("cookies"),
            message="Authentication successful"
        )

    except Exception as e:
        logging.exception("Error in F1 TV Pro authentication")
        raise HTTPException(
            status_code=401,
            detail=f"F1 TV Pro authentication failed: {str(e)}"
        )


@app.post("/authenticate-f1tv/browser-start", response_model=StartBrowserAuthResponse)
async def start_browser_auth() -> StartBrowserAuthResponse:
    """
    Start the browser-based F1TV login flow (FastF1 Companion extension / the
    f1login.fastf1.dev relay - see ATTRIBUTION.md and utils/f1_auth.py). Returns a
    URL for the caller to open themselves; poll /authenticate-f1tv/browser-status
    afterwards to learn when the login completes. Your F1TV password never reaches
    this backend - only the resulting token, once you've logged in on that page.
    """
    try:
        auth_url = f1_auth.start_browser_auth_flow()
        return StartBrowserAuthResponse(auth_url=auth_url)
    except Exception as e:
        logging.exception("Error starting browser-based F1TV auth flow")
        raise HTTPException(status_code=500, detail=f"Failed to start browser auth flow: {str(e)}")


@app.get("/authenticate-f1tv/browser-status", response_model=BrowserAuthStatusResponse)
async def browser_auth_status() -> BrowserAuthStatusResponse:
    """Poll the in-flight browser-based F1TV login flow started by /authenticate-f1tv/browser-start."""
    status = f1_auth.check_browser_auth_status()
    return BrowserAuthStatusResponse(**status)


@app.get("/f1tv-token/status", response_model=TokenStatusResponse)
async def get_f1tv_token_status() -> TokenStatusResponse:
    """Check whether the currently saved F1TV token is valid and non-expired - polled
    by the frontend before starting a live stream, and to re-check after the user
    pastes in a fresh token."""
    validity = f1_auth.describe_token_validity(f1_auth.get_saved_token())
    return TokenStatusResponse(valid=validity.valid, reason=validity.reason, expires_at=validity.expires_at)


@app.post("/f1tv-token", response_model=TokenStatusResponse)
async def update_f1tv_token(request: UpdateTokenRequest) -> TokenStatusResponse:
    """Validate a freshly-pasted F1TV token and, only if valid, save it as the new saved token."""
    validity = f1_auth.describe_token_validity(request.token)
    if validity.valid:
        f1_auth.save_token(request.token)
    return TokenStatusResponse(valid=validity.valid, reason=validity.reason, expires_at=validity.expires_at)


@app.get("/team-driver-pool", response_model=GetTeamDriverPoolResponse)
async def get_team_driver_pool_endpoint(season_year: int = CURRENT_SEASON_YEAR) -> GetTeamDriverPoolResponse:
    """
    The known per-team driver pool (race-seat and reserve/development drivers) for a season -
    used to pre-fill and validate the pre-race lineup confirmation step before a live stream
    starts (see ConfirmedRosterEntry for why that step exists).
    """
    try:
        drivers = await get_team_driver_pool(season_year)
        return GetTeamDriverPoolResponse(season_year=season_year, drivers=drivers)
    except Exception as e:
        logging.exception("Error fetching team driver pool for season_year=%s", season_year)
        raise HTTPException(status_code=500, detail=f"Failed to fetch team driver pool: {str(e)}")


@app.post("/start-live-stream", response_model=StartStreamResponse)
async def start_live_stream(request: StartStreamRequest) -> StartStreamResponse:
    """
    Start a live stream from F1's SignalR client.

    - Receives F1 TV Pro authentication tokens from frontend
    - Connects to F1 SignalR hub
    - Logs all events to console and saves to a unique file
    - Returns stream information
    """
    try:
        logging.info("Request: starting live stream")

        token = request.access_token

        if not token:
            # A missing/expired token doesn't just break team-radio audio - CarData.z
            # and Position.z (car telemetry/position) silently never arrive either,
            # with no error anywhere. So unlike the old behavior here, a bad saved
            # token now hard-fails rather than proceeding unauthenticated; the
            # frontend gates /start-live-stream on GET /f1tv-token/status first and
            # walks the user through POST /f1tv-token if this fires.
            logging.info("No access token in request, attempting to load saved token")
            saved_token = f1_auth.get_saved_token()
            validity = f1_auth.describe_token_validity(saved_token)
            if not validity.valid:
                raise HTTPException(
                    status_code=401,
                    detail=validity.reason or "No valid F1TV token configured - update your token before starting a live stream.",
                )
            token = saved_token
            logging.info("Using saved subscription token")

        streamer = live_stream.start_stream(
            access_token=token,
            refresh_token=request.refresh_token,
            cookies=request.cookies,
            confirmed_roster=request.confirmed_roster,
        )

        stream_info = streamer.get_stream_info()

        logging.info(
            "Response: live stream started successfully. stream_id=%s, log_file=%s",
            stream_info["stream_id"],
            stream_info["log_file"]
        )

        return StartStreamResponse(
            success=True,
            message="Live stream started successfully",
            stream_id=stream_info["stream_id"],
            log_file=stream_info["log_file"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error starting live stream")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start live stream: {str(e)}"
        )


@app.post("/simulate-live-stream", response_model=StartStreamResponse)
async def simulate_live_stream(request: SimulateStreamRequest = SimulateStreamRequest()) -> StartStreamResponse:
    """
    Start a replay of a captured stream_logs/*.jsonl file, driven through the
    exact same pipeline a live SignalR session uses (utils/live_session_pipeline.py).
    This is the primary way to develop against and demo Race Mode without a
    live F1TV connection - defaults to the full captured Qatar GP race.
    """
    log_path = Path("stream_logs") / request.log_file
    try:
        stream_id = replay.start_replay(
            log_path, speed_factor=request.speed_factor, confirmed_roster=request.confirmed_roster
        )
        logging.info("Started replay stream_id=%s log_file=%s speed_factor=%s", stream_id, log_path, request.speed_factor)
        return StartStreamResponse(
            success=True,
            message="Simulation started",
            stream_id=stream_id,
            log_file=str(log_path),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")
    except Exception as e:
        logging.exception("Error starting simulation")
        raise HTTPException(status_code=500, detail=f"Failed to start simulation: {str(e)}")


def _latest_live_capture_log() -> Optional[Path]:
    """The most recently modified stream_logs/live_*.jsonl - written by an in-progress
    scripts/capture_stream.py process. None if no capture is (or ever was) running."""
    candidates = sorted(STREAM_LOGS_DIR.glob("live_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _log_path_for_stream_id(stream_id: str) -> Optional[Path]:
    """Reverse of live_tail's stream_id naming (live_<session_name>) - used by the SSE
    endpoint's auto-reattach so a backend restart can rediscover which file a given
    stream_id belongs to."""
    if not stream_id.startswith("live_"):
        return None
    candidate = STREAM_LOGS_DIR / f"{stream_id}.jsonl"
    return candidate if candidate.exists() else None


@app.post("/attach-live-stream", response_model=StartStreamResponse)
async def attach_live_stream(request: AttachStreamRequest = AttachStreamRequest()) -> StartStreamResponse:
    """
    Attach the backend to an in-progress standalone capture (scripts/capture_stream.py)
    by tailing its raw jsonl file, rather than opening a second, backend-owned SignalR
    connection (see /start-live-stream for that path). This is the intended way to watch
    a session the standalone capture process is already recording: the capture keeps
    running independent of the backend, so restarting the backend and calling this again
    just re-attaches and catches straight back up - see utils/live_tail.py.
    """
    try:
        if request.session_name:
            log_path = STREAM_LOGS_DIR / f"live_{request.session_name}.jsonl"
        else:
            log_path = _latest_live_capture_log()
            if log_path is None:
                raise HTTPException(status_code=404, detail="No live capture found under stream_logs/live_*.jsonl")

        stream_id = live_tail.start_tail(log_path, confirmed_roster=request.confirmed_roster)
        logging.info("Attached to live capture: stream_id=%s log_file=%s", stream_id, log_path)
        return StartStreamResponse(
            success=True, message="Attached to live capture", stream_id=stream_id, log_file=str(log_path)
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.exception("Error attaching to live capture")
        raise HTTPException(status_code=500, detail=f"Failed to attach to live capture: {str(e)}")


@app.get("/live-stream/current", response_model=CurrentLiveStreamResponse)
async def get_current_live_stream() -> CurrentLiveStreamResponse:
    """
    Discover the currently-active standalone capture (if any) - lets the frontend find
    and (re)connect to it without hardcoding a session name, including after its own
    reload/reconnect following a backend restart.
    """
    log_path = _latest_live_capture_log()
    if log_path is None:
        raise HTTPException(status_code=404, detail="No live capture found under stream_logs/live_*.jsonl")
    session_name = log_path.stem[len("live_"):]
    return CurrentLiveStreamResponse(session_name=session_name, stream_id=log_path.stem, log_file=str(log_path))


@app.get("/live/{stream_id}/events")
async def stream_live_events(stream_id: str, request: Request) -> EventSourceResponse:
    """
    Server-Sent Events stream for a live or replayed session: an initial
    `snapshot` event carrying the full current state, then named diff events
    as they happen. Chosen over WebSocket because the traffic here is
    almost entirely one-directional (server -> client) and EventSource's
    built-in reconnect/Last-Event-ID handling covers the resume-on-reconnect
    case for free - see the product investigation artifact's SSE-vs-WebSocket
    discussion for the full reasoning.
    """
    pipeline = get_pipeline(stream_id)
    if pipeline is None:
        # The pipeline is only ever in-memory - lost on a backend restart. If this
        # stream_id is a live-capture tail (see utils/live_tail.py's naming), the raw
        # archive itself is untouched (the standalone capture process owns it, not the
        # backend - see scripts/capture_stream.py), so we can transparently re-attach
        # and catch back up instead of 404ing. This is what makes a backend restart
        # invisible to the frontend beyond a brief reconnect.
        log_path = _log_path_for_stream_id(stream_id)
        if log_path is not None:
            logging.info("No in-memory pipeline for stream_id=%s - re-attaching from %s", stream_id, log_path)
            live_tail.start_tail(log_path, stream_id=stream_id)
            pipeline = get_pipeline(stream_id)

    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"No active session for stream_id={stream_id}")

    subscriber_id, queue = pipeline.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await queue.get()
                yield {
                    "id": str(message["id"]),
                    "event": message["event"],
                    "data": json.dumps(message["data"], default=str),
                }
        finally:
            pipeline.unsubscribe(subscriber_id)

    return EventSourceResponse(event_generator())


@app.get("/lap-comparison/{session_key}")
async def get_lap_comparison(
    session_key: int,
    driver_a: int,
    lap_a: int,
    driver_b: int,
    lap_b: int,
) -> LapComparisonResponse:
    """
    Distance-aligned telemetry comparison between two completed laps -
    speed/throttle/brake/acceleration traces plus the delta-time trace and
    inferred corner locations (see utils/lap_comparison.py for how both are
    derived - F1's feed gives neither directly). Works for any two laps
    already persisted to lap_telemetry/lap_car_position, live or historical.
    """
    try:
        telemetry_a, position_a, telemetry_b, position_b = await asyncio.gather(
            lap_telemetry_db.get_lap_telemetry(session_key, driver_a, lap_a),
            lap_telemetry_db.get_lap_position(session_key, driver_a, lap_a),
            lap_telemetry_db.get_lap_telemetry(session_key, driver_b, lap_b),
            lap_telemetry_db.get_lap_position(session_key, driver_b, lap_b),
        )

        missing = [
            label
            for label, row in [
                (f"driver {driver_a} lap {lap_a} telemetry", telemetry_a),
                (f"driver {driver_a} lap {lap_a} position", position_a),
                (f"driver {driver_b} lap {lap_b} telemetry", telemetry_b),
                (f"driver {driver_b} lap {lap_b} position", position_b),
            ]
            if row is None
        ]
        if missing:
            raise HTTPException(status_code=404, detail=f"No data found for: {', '.join(missing)}")

        trace_a = build_lap_trace(
            position_a.dt_ms, position_a.x, position_a.y,
            telemetry_a.dt_ms, telemetry_a.speed, telemetry_a.throttle_pct, telemetry_a.brake_pct,
        )
        trace_b = build_lap_trace(
            position_b.dt_ms, position_b.x, position_b.y,
            telemetry_b.dt_ms, telemetry_b.speed, telemetry_b.throttle_pct, telemetry_b.brake_pct,
        )
        delta = compute_delta_trace(trace_a, trace_b)

        return LapComparisonResponse(
            session_key=session_key,
            driver_a=LapTraceResponse(
                driver_number=driver_a, lap_number=lap_a,
                distance_m=trace_a.distance_m, speed_kmh=trace_a.speed_kmh,
                throttle_pct=trace_a.throttle_pct, brake_pct=trace_a.brake_pct,
                acceleration_ms2=trace_a.acceleration_ms2,
            ),
            driver_b=LapTraceResponse(
                driver_number=driver_b, lap_number=lap_b,
                distance_m=trace_b.distance_m, speed_kmh=trace_b.speed_kmh,
                throttle_pct=trace_b.throttle_pct, brake_pct=trace_b.brake_pct,
                acceleration_ms2=trace_b.acceleration_ms2,
            ),
            delta=DeltaTraceResponse(
                distance_m=delta.distance_m,
                delta_seconds=delta.delta_seconds,
                corners=[
                    CornerResponse(distance_m=c.distance_m, apex_speed_kmh=c.apex_speed_kmh) for c in delta.corners
                ],
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error computing lap comparison for session_key=%s", session_key)
        raise HTTPException(status_code=500, detail=f"Failed to compute lap comparison: {str(e)}")


@app.get("/team-radio/{session_key}")
async def get_team_radio(session_key: int) -> GetTeamRadioResponse:
    """
    All team radio clips for a session - the same table and query path
    whether the session is still live/replaying or long finished. Audio
    files are served from the `/audio` static mount at each clip's `audio_path`.
    """
    try:
        clips = await team_radio_db.get_for_session(session_key)
        return GetTeamRadioResponse(session_key=session_key, clips=clips)
    except Exception as e:
        logging.exception("Error fetching team radio for session_key=%s", session_key)
        raise HTTPException(status_code=500, detail=f"Failed to fetch team radio: {str(e)}")
