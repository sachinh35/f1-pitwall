-- Tags each lap_data row with the qualifying segment it was set in (Q1/Q2/Q3, NULL for a
-- non-qualifying session) and whether it was later deleted (track limits, impeding, etc.)
-- - see utils/session_state.py's qualifying_part/DeletedLap and utils/live_persistence.py.
ALTER TABLE lap_data ADD COLUMN IF NOT EXISTS qualifying_part VARCHAR(2);
ALTER TABLE lap_data ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_lap_data_qualifying_part ON lap_data (session_key, qualifying_part);
