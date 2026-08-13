-- 0014: team_radio had no idempotency at all - unlike weather_snapshots/race_control_events
-- (see 0012_live_persist_idempotency.sql), every re-simulation/re-tail of the same archive
-- re-downloaded, re-transcribed (Whisper), and re-analyzed (Gemini) every single radio
-- capture from scratch, since SessionState._seen_radio_paths only dedupes in-memory within
-- one process's lifetime. Confirmed against session_key=11338: 208 rows for 16 real distinct
-- captures after a handful of dev replay runs.
--
-- capture_path is F1's own raw TeamRadio.Captures[].Path (e.g. "TeamRadio/x.mp3") - stable
-- and unique per real capture within a session, unlike ts (F1's own Utc field, which we
-- already parse and dedupe on, but two genuinely distinct clips could in principle share a
-- timestamp) or driver+lap (multiple radio calls can happen on the same lap). NULL-safe
-- partial unique index, matching uq_race_control_session_message_index's pattern, so it
-- never blocks a row inserted before this migration (capture_path IS NULL there).
ALTER TABLE team_radio
    ADD COLUMN IF NOT EXISTS capture_path TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_radio_session_capture_path
    ON team_radio (session_key, capture_path)
    WHERE capture_path IS NOT NULL;
