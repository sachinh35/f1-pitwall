---
title: Setup
---

## Docker (recommended)

Requires Docker and `make`.

```bash
git clone https://github.com/sachinh35/f1-pitwall.git
cd f1-pitwall
cp .env.example .env   # optional, see Environment variables below
make
```

`make` (the default target) runs, in order:

1. Backend test suite (`pytest`) and frontend test suite (`vitest`), each
   gated on **>=95% coverage** - stops here if either fails.
2. `docker compose build` for the backend and frontend images. The backend
   build also downloads the Whisper model used for team-radio transcription
   (~487MB), so first build takes a few minutes.
3. `docker compose up` - starts `db`, `migrate`, `backend` (`:8000`), and
   `frontend` (`:5173`) in dependency order.

Other targets: `make test` (just the test/coverage gate), `make build`
(test + build images, no run), `make down` (stop, keep data), `make clean`
(stop and delete the Postgres volume), `make logs` (tail all service logs).

## Local development (without Docker)

Backend:

```bash
cd backend
uv sync
uv run uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

You'll need a local Postgres instance either way -
`backend/config/database_config.py` reads
`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_PASSWORD` from the environment
(all optional; defaults assume a passwordless local Postgres).

## Environment variables

Set these in a root-level `.env` (gitignored; `docker-compose.yml` loads it
automatically) - see `.env.example` for the full list with defaults.

| Variable | Used by | Purpose |
|---|---|---|
| `DB_USER`, `DB_NAME`, `DB_HOST`, `DB_PORT`, `DB_PASSWORD` | `migrate`, `backend` | Postgres connection. Defaults match the compose-managed `db` service. |
| `GEMINI_API_KEY`, `GEMINI_MODEL_ID` | `backend` | Optional - only needed for the team-radio "notable message" classifier. Everything else works without it. |

### Pointing at a Postgres you already have running

By default `docker-compose.yml` starts its own Postgres (`db` service, with
a named volume so data survives restarts). If you already run Postgres
natively and want the containers to use that instead, set in `.env`:

```bash
DB_HOST=host.docker.internal
DB_PORT=5432
DB_USER=your-local-username
DB_PASSWORD=
```

`host.docker.internal` works out of the box on Docker Desktop (Mac/Windows);
on Linux you'd need to add `extra_hosts: ["host.docker.internal:host-gateway"]`
to the `migrate`/`backend` services in `docker-compose.yml` first. Note the
compose-managed `db` service still starts either way - it's just unused.

Your local Postgres also needs to actually accept TCP connections from
Docker's network, not just local Unix-socket connections - check
`listen_addresses` and `pg_hba.conf` if the connection is refused.

## Team radio transcription

The backend image bakes in the Whisper model (`ggml-small.bin`) at build
time, so transcription works out of the box - no separate download or
volume mount needed. Classifying transcripts (driver vs. pit-wall, flagging
notable messages) is a separate step gated on `GEMINI_API_KEY`.

## Running a simulation

Rather than connecting to F1's live feed, you can replay a captured session:

```bash
curl -X POST http://localhost:8000/simulate-live-stream \
  -H "Content-Type: application/json" \
  -d '{"log_file": "some_capture.jsonl", "speed_factor": 20}'
```

This returns a `stream_id` - open `http://localhost:5173/live-stream/{stream_id}`
to watch it. `log_file` must be a filename under `backend/stream_logs/`
(gitignored - raw captures aren't committed to source control).
