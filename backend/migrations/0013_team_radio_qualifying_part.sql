-- 0013: tag each team_radio capture with the qualifying segment it was captured in
-- (Q1/Q2/Q3), enriched at ingest from the live reducer's SessionState.qualifying_part -
-- never present in F1's raw TeamRadio message, same pattern as lap_number. NULL for a
-- race session (qualifying_part is only ever set during qualifying) or a capture that
-- arrived before SessionInfo established the session type.
ALTER TABLE team_radio
    ADD COLUMN IF NOT EXISTS qualifying_part VARCHAR(2);
