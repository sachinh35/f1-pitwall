"""
ConfirmedRosterEntry lives in its own module (rather than alongside the other
live_stream.py request/response models) so utils/live_stream.py, utils/replay.py,
utils/live_session_pipeline.py, and utils/live_persistence.py can all import it
without pulling in api_pydantic_models/live_stream.py's other dependencies
(utils.team_radio_db -> utils/__init__.py -> utils.live_stream - a circular
import back to this exact module, confirmed by actually booting the app rather
than just running pytest, whose import order happened not to trigger it).
"""
from pydantic import BaseModel, Field
from typing import Optional


class ConfirmedRosterEntry(BaseModel):
    """One driver in a user-confirmed pre-race lineup - see /team-driver-pool.

    Supplied by the frontend's lineup-confirmation step before a live stream
    starts, since OpenF1's free-tier REST access can't be relied on for a
    genuinely in-progress session (see utils/session_metadata.py). Taking this
    as explicit input is what lets a reserve/substitute driver be represented
    correctly even though the automatic OpenF1 fetch can't see them yet.
    """
    driver_number: int = Field(..., description="Car number this driver is racing under this session")
    tla: str = Field(..., description="Three-letter driver code, e.g. 'VER'")
    full_name: str = Field(..., description="Driver's full name")
    team_name: str = Field(..., description="Constructor/team name")
    team_colour: Optional[str] = Field(None, description="Team accent hex color, e.g. '#3671C6' - resolved client-side")
