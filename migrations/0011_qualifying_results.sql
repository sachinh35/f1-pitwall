-- One row per driver per qualifying segment's final standing (position, best lap, gap to
-- the segment leader, eliminated) - a durable snapshot taken the moment each segment ends
-- (Q1->Q2/Q2->Q3 transition, or SessionStatus "Finalised" for the last segment), so this is
-- retrievable directly instead of replaying/recomputing from the raw stream - see
-- utils/session_state.py's QualifyingResultEntry and utils/live_persistence.py.
CREATE TABLE IF NOT EXISTS qualifying_results (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    meeting_key INTEGER,
    driver_number INTEGER NOT NULL,
    qualifying_part VARCHAR(2) NOT NULL,
    position INTEGER,
    best_lap_seconds DECIMAL(10, 3),
    gap_to_leader_seconds DECIMAL(10, 3),
    eliminated BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_qualifying_result UNIQUE (session_key, qualifying_part, driver_number)
);

CREATE INDEX IF NOT EXISTS idx_qualifying_results_session ON qualifying_results (session_key, qualifying_part);
