-- 0002: derived per-lap telemetry aggregates, computed once when a lap completes
-- (avg/max speed, avg throttle, DRS-active share) - never recomputed from raw
-- arrays on read.

ALTER TABLE lap_data
    ADD COLUMN IF NOT EXISTS avg_speed_kmh SMALLINT,
    ADD COLUMN IF NOT EXISTS max_speed_kmh SMALLINT,
    ADD COLUMN IF NOT EXISTS avg_throttle_pct SMALLINT,
    ADD COLUMN IF NOT EXISTS drs_active_pct SMALLINT;
