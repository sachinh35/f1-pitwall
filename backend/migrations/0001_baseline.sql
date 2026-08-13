-- 0001: Baseline schema, expressed idempotently.
-- Everything here already exists in the running database (created by hand before
-- this migration runner existed) - this file exists so a *fresh* database reaches
-- the same starting point, and so it's safe to re-run against the current one.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- lap_data
CREATE TABLE IF NOT EXISTS lap_data (
    id SERIAL PRIMARY KEY,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    date_start TIMESTAMP,
    duration_sector_1 DECIMAL(10, 3),
    duration_sector_2 DECIMAL(10, 3),
    duration_sector_3 DECIMAL(10, 3),
    lap_duration DECIMAL(10, 3),
    i1_speed INTEGER,
    i2_speed INTEGER,
    st_speed INTEGER,
    is_pit_out_lap BOOLEAN DEFAULT FALSE,
    segments_sector_1 INTEGER[],
    segments_sector_2 INTEGER[],
    segments_sector_3 INTEGER[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_lap_per_driver_session UNIQUE(session_key, driver_number, lap_number)
);

CREATE INDEX IF NOT EXISTS idx_session_driver_lap ON lap_data(session_key, driver_number, lap_number);
CREATE INDEX IF NOT EXISTS idx_session_key ON lap_data(session_key);
CREATE INDEX IF NOT EXISTS idx_meeting_key ON lap_data(meeting_key);
CREATE INDEX IF NOT EXISTS idx_driver_number ON lap_data(driver_number);

DROP TRIGGER IF EXISTS update_lap_data_updated_at ON lap_data;
CREATE TRIGGER update_lap_data_updated_at
    BEFORE UPDATE ON lap_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- stints
CREATE TABLE IF NOT EXISTS stints (
    id SERIAL PRIMARY KEY,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    stint_number INTEGER NOT NULL,
    lap_start INTEGER NOT NULL,
    lap_end INTEGER NOT NULL,
    compound VARCHAR(20),
    tyre_age_at_start INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_stint_per_driver_session UNIQUE(session_key, driver_number, stint_number)
);

CREATE INDEX IF NOT EXISTS idx_stints_session ON stints(session_key);
CREATE INDEX IF NOT EXISTS idx_stints_session_driver ON stints(session_key, driver_number);

DROP TRIGGER IF EXISTS update_stints_updated_at ON stints;
CREATE TRIGGER update_stints_updated_at
    BEFORE UPDATE ON stints
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- race_control_events
CREATE TABLE IF NOT EXISTS race_control_events (
    id SERIAL PRIMARY KEY,
    meeting_key INTEGER NOT NULL,
    session_key INTEGER NOT NULL,
    date TIMESTAMP NOT NULL,
    category VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    scope VARCHAR(20),
    sector INTEGER,
    driver_number INTEGER,
    flag VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_race_control_session ON race_control_events(session_key);
CREATE INDEX IF NOT EXISTS idx_race_control_session_date ON race_control_events(session_key, date);
CREATE INDEX IF NOT EXISTS idx_race_control_driver ON race_control_events(session_key, driver_number) WHERE driver_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_race_control_sector ON race_control_events(session_key, sector) WHERE sector IS NOT NULL;

DROP TRIGGER IF EXISTS update_race_control_events_updated_at ON race_control_events;
CREATE TRIGGER update_race_control_events_updated_at
    BEFORE UPDATE ON race_control_events
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- live_streams / live_lap_times (write-side staging tables while a session is live)
CREATE TABLE IF NOT EXISTS live_streams (
    id SERIAL PRIMARY KEY,
    stream_id VARCHAR(50) NOT NULL UNIQUE,
    race_name VARCHAR(255),
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_lap_times (
    id SERIAL PRIMARY KEY,
    stream_id VARCHAR(50) NOT NULL REFERENCES live_streams(stream_id),
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    lap_time DECIMAL(10, 3),
    sector_1 DECIMAL(10, 3),
    sector_2 DECIMAL(10, 3),
    sector_3 DECIMAL(10, 3),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_live_lap_per_driver UNIQUE(stream_id, driver_number, lap_number)
);

CREATE INDEX IF NOT EXISTS idx_live_lap_times_stream ON live_lap_times(stream_id);
CREATE INDEX IF NOT EXISTS idx_live_lap_times_stream_driver ON live_lap_times(stream_id, driver_number);
