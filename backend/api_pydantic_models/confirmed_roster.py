"""
ConfirmedRosterEntry lives in its own module (rather than alongside the other
live_stream.py request/response models) so live/live_stream.py, live/replay.py,
live/live_session_pipeline.py, and db/live_persistence.py can all import it
without pulling in api_pydantic_models/live_stream.py's other dependencies.

Historically (back when db/, live/, etc. were all one flat `utils` package)
that mattered because utils/__init__.py eagerly imported several submodules,
so importing utils.team_radio_db transitively loaded utils.live_stream too -
a circular import back to this exact module, confirmed by actually booting
the app rather than just running pytest, whose import order happened not to
trigger it. Now that live/, db/, team_radio/, etc. are separate packages with
empty __init__.py files, importing db.team_radio_db no longer pulls in
live.live_stream at all, but the split is kept anyway - it's still the
narrower, more obviously-correct import for the live-path modules to take.
"""
from pydantic import BaseModel, Field
from typing import Optional


class ConfirmedRosterEntry(BaseModel):
    """One driver in a user-confirmed pre-race lineup - see /team-driver-pool.

    Supplied by the frontend's lineup-confirmation step before a live stream
    starts, since OpenF1's free-tier REST access can't be relied on for a
    genuinely in-progress session (see db/session_metadata.py). Taking this
    as explicit input is what lets a reserve/substitute driver be represented
    correctly even though the automatic OpenF1 fetch can't see them yet.
    """
    driver_number: int = Field(..., description="Car number this driver is racing under this session")
    tla: str = Field(..., description="Three-letter driver code, e.g. 'VER'")
    full_name: str = Field(..., description="Driver's full name")
    team_name: str = Field(..., description="Constructor/team name")
    team_colour: Optional[str] = Field(None, description="Team accent hex color, e.g. '#3671C6' - resolved client-side")
