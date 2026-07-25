"""
Pydantic models for live streaming API requests and responses.
"""
from pydantic import BaseModel, Field
from typing import List, Optional

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from utils.team_radio_db import TeamRadioDB


class StartStreamRequest(BaseModel):
    """Request model for starting a live stream."""
    access_token: Optional[str] = Field(None, description="F1 TV Pro access token for authentication (optional if saved token exists)")
    refresh_token: Optional[str] = Field(None, description="F1 TV Pro refresh token (optional)")
    cookies: Optional[str] = Field(None, description="F1 TV Pro session cookies (optional)")
    confirmed_roster: Optional[List[ConfirmedRosterEntry]] = Field(
        None, description="User-confirmed pre-race lineup - see ConfirmedRosterEntry"
    )


class AuthenticateRequest(BaseModel):
    """Request model for F1 TV Pro authentication."""
    email: str = Field(..., description="F1 TV Pro account email")
    password: str = Field(..., description="F1 TV Pro account password")


class AuthenticateResponse(BaseModel):
    """Response model for F1 TV Pro authentication."""
    success: bool = Field(..., description="Whether authentication was successful")
    access_token: str = Field(..., description="F1 TV Pro access token")
    cookies: Optional[str] = Field(None, description="Session cookies")
    message: Optional[str] = Field(None, description="Status message")


class StartBrowserAuthResponse(BaseModel):
    """Response model for starting the browser-based (FastF1 Companion) auth flow."""
    auth_url: str = Field(..., description="URL to open in a browser to complete F1TV login")


class BrowserAuthStatusResponse(BaseModel):
    """Response model for polling the browser-based auth flow's progress."""
    status: str = Field(..., description="One of: not_started, pending, authenticated, failed")
    auth_url: Optional[str] = Field(None, description="Present while status is 'pending' - the URL to open")
    error: Optional[str] = Field(None, description="Present only when status is 'failed'")


class StartStreamResponse(BaseModel):
    """Response model for starting a live stream."""
    success: bool = Field(..., description="Whether the stream was started successfully")
    message: str = Field(..., description="Status message")
    stream_id: str = Field(..., description="Unique identifier for this stream session")
    log_file: str = Field(..., description="Path to the log file where stream data is being saved")


class SimulateStreamRequest(BaseModel):
    """Request model for starting a replay of a captured stream_logs/*.jsonl file."""
    log_file: str = Field(
        default="f1_stream_1764517880_race_qatar.jsonl",
        description="Filename under stream_logs/ to replay",
    )
    speed_factor: float = Field(
        default=20.0,
        gt=0,
        description="Playback speed multiplier - the real gaps between messages, scaled down by this factor",
    )
    confirmed_roster: Optional[List[ConfirmedRosterEntry]] = Field(
        None, description="User-confirmed pre-race lineup - see ConfirmedRosterEntry"
    )


class AttachStreamRequest(BaseModel):
    """Request model for attaching the backend to an in-progress standalone capture
    (scripts/capture_stream.py) by tailing its raw jsonl file - see utils/live_tail.py."""
    session_name: Optional[str] = Field(
        None,
        description="Matches scripts/capture_stream.py's --session-name - resolves to "
        "stream_logs/live_<session_name>.jsonl. If omitted, attaches to whichever live_*.jsonl "
        "file was most recently modified.",
    )
    confirmed_roster: Optional[List[ConfirmedRosterEntry]] = Field(
        None, description="User-confirmed pre-race lineup - see ConfirmedRosterEntry"
    )


class CurrentLiveStreamResponse(BaseModel):
    """Response model for discovering the currently-active standalone capture, if any."""
    session_name: str = Field(..., description="The session name, e.g. quali_2026_07_25")
    stream_id: str = Field(..., description="The stream_id to connect GET /live/{stream_id}/events to")
    log_file: str = Field(..., description="Path to the raw jsonl file under stream_logs/")


class TeamDriverPoolEntry(BaseModel):
    """One driver in a team's known season pool (race-seat or reserve) - see /team-driver-pool."""
    team_name: str
    driver_number: Optional[int] = None
    tla: Optional[str] = None
    full_name: str
    is_reserve: bool


class GetTeamDriverPoolResponse(BaseModel):
    season_year: int
    drivers: List[TeamDriverPoolEntry]


class GetTeamRadioResponse(BaseModel):
    """Response model for fetching a session's team radio clips - live or historical, same table."""
    session_key: int
    clips: List[TeamRadioDB]

