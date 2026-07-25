-- Fixes a real bug: persist_weather_snapshot/persist_race_control_entry were plain INSERTs
-- with no dedup key, so re-tailing/replaying a session's raw archive (which the backend now
-- does routinely on every restart - see utils/live_tail.py) re-inserted the entire historical
-- sequence every time. weather_snapshots.ts also used INSERT-time (CURRENT_TIMESTAMP) rather
-- than the real captured event time, so replayed rows clustered at the replay moment instead
-- of reflecting the actual session timeline - see utils/session_state.py's StateDiff.event_time.
--
-- race_control_events is shared with the historical OpenF1-backed batch-insert path (see
-- utils/race_control.py), which has no concept of message_index - those rows keep it NULL,
-- and NULL is never considered equal to NULL by a unique index, so they're unaffected by the
-- new constraint. It only actually de-duplicates the live/replayed path, which always sets it.
ALTER TABLE race_control_events ADD COLUMN IF NOT EXISTS message_index INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS uq_race_control_session_message_index
    ON race_control_events (session_key, message_index);

ALTER TABLE weather_snapshots ADD CONSTRAINT uq_weather_snapshots_session_ts UNIQUE (session_key, ts);
