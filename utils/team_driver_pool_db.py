"""
Read access to `team_driver_pool` - the known per-team roster (race-seat and
reserve/development drivers) for a season, seeded by migrations/0006_team_driver_pool.sql.
Used to populate the pre-race lineup confirmation step (see api_pydantic_models/live_stream.py's
ConfirmedRosterEntry for why that step exists).
"""
from __future__ import annotations

from typing import List

from api_pydantic_models.live_stream import TeamDriverPoolEntry
from utils.database import DatabaseManager


async def get_team_driver_pool(season_year: int) -> List[TeamDriverPoolEntry]:
    """All known drivers (race-seat and reserve) for a season, grouped implicitly by team_name -
    ordered so each team's race-seat drivers come before its reserves."""
    async with DatabaseManager.get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT team_name, driver_number, tla, full_name, is_reserve
            FROM team_driver_pool
            WHERE season_year = $1
            ORDER BY team_name, is_reserve, full_name
            """,
            season_year,
        )
    return [
        TeamDriverPoolEntry(
            team_name=row["team_name"],
            driver_number=row["driver_number"],
            tla=row["tla"],
            full_name=row["full_name"],
            is_reserve=row["is_reserve"],
        )
        for row in rows
    ]
