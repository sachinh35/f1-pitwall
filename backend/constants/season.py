from datetime import datetime, timezone

# The default season year for endpoints/queries that need one but have no session_key (and
# therefore no sessions.year/driver_roster.year) to derive it from yet - e.g. team_driver_pool
# and driver_roster reads that run before a session has actually started.
CURRENT_SEASON_YEAR: int = datetime.now(timezone.utc).year
