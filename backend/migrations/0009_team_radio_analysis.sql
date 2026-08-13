-- 0009: Gemini-classified fields for team radio, populated right after transcription
-- by utils/radio_analysis.py:
--   - speaker_role: who's most likely talking (driver vs pit wall) - F1's raw feed
--     carries no speaker/diarization info at all, so this is an LLM inference over the
--     transcript text, not ground truth.
--   - is_notable / notable_reason: whether this message is broadcast-worthy (box calls,
--     incidents, overtakes, retirements, etc.), surfaced in the "Notable Radio" widget.

ALTER TABLE team_radio
    ADD COLUMN IF NOT EXISTS speaker_role VARCHAR(20),
    ADD COLUMN IF NOT EXISTS is_notable BOOLEAN,
    ADD COLUMN IF NOT EXISTS notable_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_team_radio_notable ON team_radio(session_key, is_notable);
