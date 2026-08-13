-- 0008: total scheduled race laps, resolved from OpenF1's /v1/laps (the max
-- lap_number seen) since F1's live SignalR feed never sends this - confirmed
-- by enumerating every LapCount message across a full captured race: every
-- one ever contains only {"CurrentLap": N}, never a total. Nullable: for a
-- genuinely live/future session, OpenF1 won't have any lap records yet
-- either, so this stays unknown until laps have actually been recorded.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS total_laps INTEGER;
