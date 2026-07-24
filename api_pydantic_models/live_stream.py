"""
Pydantic models for live streaming API requests and responses.
"""
from pydantic import BaseModel, Field
from typing import List, Optional

from utils.team_radio_db import TeamRadioDB


class StartStreamRequest(BaseModel):
    """Request model for starting a live stream."""
    access_token: Optional[str] = Field(None, description="F1 TV Pro access token for authentication (optional if saved token exists)")
    refresh_token: Optional[str] = Field(None, description="F1 TV Pro refresh token (optional)")
    cookies: Optional[str] = Field(None, description="F1 TV Pro session cookies (optional)")


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


class GetTeamRadioResponse(BaseModel):
    """Response model for fetching a session's team radio clips - live or historical, same table."""
    session_key: int
    clips: List[TeamRadioDB]

