-- 0005: session metadata (circuit/location/date/session type) and the driver
-- roster actually entered for a given session, both fetched from OpenF1 once
-- a live/simulated session's SessionInfo message reveals its session_key.
--
-- Neither existed before this migration: the live SignalR feed's own
-- DriverList topic never carries names/teams (see driverRoster.ts on the
-- frontend), and nothing persisted race details (circuit, date, session
-- type) locally at all - every existing table only ever stored the bare
-- meeting_key/session_key integers.

CREATE TABLE IF NOT EXISTS sessions (
    session_key INTEGER PRIMARY KEY,
    meeting_key INTEGER NOT NULL,
    session_name VARCHAR(50) NOT NULL,
    session_type VARCHAR(50) NOT NULL,
    circuit_key INTEGER,
    circuit_short_name VARCHAR(100),
    country_code VARCHAR(10),
    country_name VARCHAR(100),
    location VARCHAR(100),
    date_start TIMESTAMP,
    date_end TIMESTAMP,
    gmt_offset VARCHAR(20),
    year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_meeting_key ON sessions(meeting_key);

-- Keyed by session_key, not meeting_key: a reserve/substitute driver can
-- change the entered roster from one session to the next within the same
-- race weekend, so a meeting-level roster would be wrong as soon as that
-- happens.
CREATE TABLE IF NOT EXISTS driver_roster (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    broadcast_name VARCHAR(100),
    full_name VARCHAR(100) NOT NULL,
    name_acronym VARCHAR(10) NOT NULL,
    team_name VARCHAR(100),
    team_colour VARCHAR(10),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    headshot_url TEXT,
    country_code VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_driver_roster_per_session UNIQUE(session_key, driver_number)
);

CREATE INDEX IF NOT EXISTS idx_driver_roster_session ON driver_roster(session_key);
