-- 0007: durable storage for Battle Radar's gap-to-car-ahead, captured at the
-- same lap-boundary event as the other derived per-lap aggregates (0002) -
-- so the live "is this driver closing in" trend survives a backend restart
-- or reconnect instead of living only in the in-memory reducer.

ALTER TABLE lap_data
    ADD COLUMN IF NOT EXISTS gap_to_ahead_seconds NUMERIC(6, 3);
