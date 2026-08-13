-- 0004: weather ticks and team-radio clips (+ their Whisper transcripts).
-- lap_number on team_radio is enriched at ingest from the live reducer state -
-- it is never present in F1's raw TeamRadio message. Indexed on (session_key,
-- driver_number, ts) and (session_key, lap_number), NOT unique on driver+lap:
-- a driver can key the radio more than once in the same lap.

CREATE TABLE IF NOT EXISTS weather_snapshots (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    air_temp DECIMAL(5, 2),
    track_temp DECIMAL(5, 2),
    humidity DECIMAL(5, 2),
    pressure DECIMAL(7, 2),
    rainfall SMALLINT,
    wind_speed DECIMAL(5, 2),
    wind_direction SMALLINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_weather_snapshots_session_ts ON weather_snapshots(session_key, ts);

CREATE TABLE IF NOT EXISTS team_radio (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER,
    ts TIMESTAMP NOT NULL,
    audio_path TEXT,
    transcript TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    error TEXT,
    transcribed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_team_radio_session_driver_ts ON team_radio(session_key, driver_number, ts);
CREATE INDEX IF NOT EXISTS idx_team_radio_session_lap ON team_radio(session_key, lap_number);
