-- driver_roster is keyed by session_key, which only gets you the year via a join to
-- `sessions` - every query pattern that wants "this season's roster" (mirroring how
-- team_driver_pool is already keyed/queried by season_year, see 0006_team_driver_pool.sql
-- and main.py's CURRENT_SEASON_YEAR) would otherwise need that join every time. Denormalize
-- year directly onto driver_roster instead, populated at write time going forward (see
-- utils/live_persistence.py's persist_driver_roster/persist_confirmed_driver_roster, which
-- already have the session's F1Session on hand at the same call site - see
-- utils/live_session_pipeline.py's _fetch_and_broadcast_session_meta).
ALTER TABLE driver_roster ADD COLUMN IF NOT EXISTS year INTEGER;

-- Backfill existing rows from sessions.year (already NULLable there - see
-- 0005_session_metadata.sql - so a row whose session was never fully persisted stays NULL
-- here too, same as it would if OpenF1's session-metadata fetch had failed for a new row).
UPDATE driver_roster dr
SET year = s.year
FROM sessions s
WHERE dr.session_key = s.session_key
  AND dr.year IS NULL;

CREATE INDEX IF NOT EXISTS idx_driver_roster_year ON driver_roster(year);
