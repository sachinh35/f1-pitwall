# Team radio pipeline sample output

A real, unmodified run of the full team-radio pipeline (download → Whisper transcription →
Gemini classification), kept here so the result is easy to inspect directly rather than only
living in logs/DB rows.

**Source clip**: Nico Hülkenberg (car #27), lap 6, 2025 Qatar Grand Prix - a real historical
F1 broadcast, captured live at the time and served from F1's own CDN
(`livetiming.formula1.com/static/...`), downloaded fresh for this sample. No authentication was
needed - see the project history for why (F1's static content CDN just requires the correct
session-rooted URL path, not a token).

## Files

- `audio.mp3` - the downloaded clip, as-is from F1's CDN.
- `transcript.txt` - `utils/whisper_transcriber.py`'s output (local Whisper, `small` model), verbatim.
- `gemini_analysis.json` - `utils/radio_analysis.py`'s output: a Strands Agent backed by Google
  Gemini (`gemini-3.5-flash-lite`) classifying the transcript. `speaker_role` is an LLM inference
  (driver vs. pit wall) - F1's raw feed carries no speaker/diarization data at all, so this is
  never ground truth, just the model's best read of the wording. `is_notable`/`notable_reason`
  are what drive the "Notable Radio" widget and the timing-tower radio indicator's highlight color
  in the frontend.

## Result

> "I can't believe this. Unbelievable. I gave him loads of space."

```json
{
  "speaker_role": "driver",
  "reasoning": "The driver is complaining angrily about another car not leaving space, which indicates an on-track incident or battle early in the race.",
  "is_notable": true,
  "notable_reason": "Nico Hulkenberg expresses extreme frustration over contact or a close call on lap 6."
}
```
