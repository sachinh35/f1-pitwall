---
title: Troubleshooting
---

## "Firefox/Chrome can't establish a connection" to `localhost:8000` or `:5173`, but curl works

Something else on your machine is already listening on that port and
shadowing the Docker container - most commonly a leftover native
`uvicorn --reload` (backend) or `vite` (frontend) process from an earlier
local-dev session. Different browsers (and even `curl` vs. a browser) can
resolve `localhost` to `127.0.0.1` vs. `::1` differently, so you can end up
hitting the stray process instead of the container depending on which one
you use.

Find and kill it:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN   # or :5173 for the frontend
kill <pid>
```

Then confirm only Docker's proxy remains:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
# should show only `com.docke...` (Docker Desktop's proxy), nothing else
```

## Pointing at a local Postgres: "connection refused" or auth errors

See [Setup - pointing at a Postgres you already have running](setup.html).
Two common causes:

- `listen_addresses` in `postgresql.conf` doesn't include the interface
  Docker connects over (check with `SHOW listen_addresses;`).
- `pg_hba.conf` only trusts local Unix-socket / `127.0.0.1` connections, and
  rejects the connection Docker's network makes on your behalf.

## `make test` fails on the coverage gate

Backend coverage: `cd backend && uv run pytest --cov=. --cov-report=term-missing`
shows exactly which files/lines are uncovered. Frontend:
`cd frontend && npx vitest run --coverage`. Both must stay >=95% (statements/
branches/functions/lines on the frontend side) for `make` to proceed past
the test stage.

## Simulation runs but nothing shows up in the browser

- Confirm you're on the specific `/live-stream/{stream_id}` URL the
  `/simulate-live-stream` response gave you, not just `/`.
- Check the backend logs (`make logs`, or `docker compose logs backend`)
  for `GET /live/{stream_id}/events` - if it's missing entirely, the
  browser never actually connected (see the port-shadowing issue above).
  If it's there but 404s, the backend was restarted (which clears
  in-progress replays) after you got that `stream_id` - start a new
  simulation and use its fresh `stream_id`.

## Team-radio transcription/classification not working

- Transcription needs the Whisper model, which is baked into the backend
  image at build time - if it's missing, the build itself would have
  failed downloading it, not silently skipped it.
- Classification (driver/pit-wall role, "notable" flagging) needs a valid
  `GEMINI_API_KEY` in `.env`. An expired/revoked key fails with a real 401
  from Google's API, not a silent no-op - check `docker compose logs backend`
  for `RuntimeError: GEMINI_API_KEY is not set` or a 401 traceback.
