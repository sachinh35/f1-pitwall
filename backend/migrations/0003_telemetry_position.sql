-- 0003: full-resolution per-lap telemetry and car-position, one row per
-- driver per completed lap (not one row per raw sample - see the product
-- investigation artifact for why).
--
-- Named `lap_car_position`, not `lap_position`, to avoid any confusion with
-- the pre-existing (and currently unused-by-any-code) `lap_positions` table,
-- which holds race position/rank per lap, not track X/Y/Z coordinates.

CREATE TABLE IF NOT EXISTS lap_telemetry (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    dt_ms INTEGER[] NOT NULL,
    speed SMALLINT[] NOT NULL,
    rpm INTEGER[] NOT NULL,
    gear SMALLINT[] NOT NULL,
    throttle_pct SMALLINT[] NOT NULL,
    brake_pct SMALLINT[] NOT NULL,
    drs SMALLINT[] NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_lap_telemetry_per_driver_session UNIQUE(session_key, driver_number, lap_number)
);

CREATE INDEX IF NOT EXISTS idx_lap_telemetry_session_driver_lap
    ON lap_telemetry(session_key, driver_number, lap_number);

CREATE TABLE IF NOT EXISTS lap_car_position (
    id SERIAL PRIMARY KEY,
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    dt_ms INTEGER[] NOT NULL,
    x INTEGER[] NOT NULL,
    y INTEGER[] NOT NULL,
    z INTEGER[] NOT NULL,
    status TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_lap_car_position_per_driver_session UNIQUE(session_key, driver_number, lap_number)
);

CREATE INDEX IF NOT EXISTS idx_lap_car_position_session_driver_lap
    ON lap_car_position(session_key, driver_number, lap_number);
