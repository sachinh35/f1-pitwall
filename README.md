# f1-dashboard
Dashboard for visualizing F1 data, live and historical.

# Run backend locally

## Without Docker

Dependencies are managed with [uv](https://docs.astral.sh/uv/). No separate install step -
`uv run` resolves and installs everything from `pyproject.toml`/`uv.lock` automatically.

Apply database migrations (safe to re-run - idempotent):
```
uv run python -m scripts.migrate
```

Start the server:
```
uv run uvicorn main:app --reload
```

Run the test suite:
```
uv run pytest
```

## With Docker

For sanity testing before publishing your PR.

```
docker build -t fastapi-backend .
docker run -p 8000:8000 fastapi-backend
```

Note: the local Whisper model used for team-radio transcription (`~/.cache/openwhispr/whisper-models`)
is not baked into the image - mount it and point `WHISPER_MODELS_DIR` at the mount:
```
docker run -p 8000:8000 \
  -v ~/.cache/openwhispr/whisper-models:/models \
  -e WHISPER_MODELS_DIR=/models \
  fastapi-backend
```

# Authenticating with F1 TV Pro (required for live sessions)

Live streaming (not simulation) needs a valid F1TV Pro subscription token. Tokens expire -
if `/start-live-stream` returns a 400 asking you to authenticate, refresh it:
```
uv run python auth_helper.py
```
This opens a browser login flow and saves the token locally; nothing to pass manually afterward.

# Example requests with cURL

## GetRacesForYear
To get races for year 2024.
```
curl http://localhost:8000/races/2024
```
## GetYears

```
curl http://localhost:8000/years
```

## GetSessionTypes

```
curl https://localhost:8000/session-types
```

## Start a live stream (requires a valid F1TV Pro token - see above)
```
curl -X POST http://localhost:8000/start-live-stream
```

## Replay a captured session instead (no F1TV Pro token needed)
Every message replayed is written to `stream_logs/` exactly like a live session -
storage isn't something you opt into separately, it happens as a side effect of
either path running.
```
curl -X POST http://localhost:8000/simulate-live-stream \
  -H "Content-Type: application/json" \
  -d '{"log_file": "f1_stream_1765029142_quali_abu_dhabi.jsonl", "speed_factor": 20}'
```

# Attribution

This project uses [FastF1](https://github.com/theOehrly/Fast-F1) for data retrieval.
