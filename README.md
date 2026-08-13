# F1 Pit Wall

A live F1 race dashboard — timing tower, race control feed, team radio, and
car telemetry, pit-wall style. Streams F1's live timing feed (or replays a
captured session) over SSE into a React dashboard, backed by Postgres for
historical queries.

- `backend/` — FastAPI + PostgreSQL (asyncpg), live-timing ingestion and REST API.
- `frontend/` — React + Vite + MUI dashboard.

Each half keeps its own `package.json`/`pyproject.toml` and can still be
deployed independently in production (e.g. frontend on Vercel, backend on
Render/Fly) — this repo just makes it possible to clone once and run the
whole stack locally.

## Quickstart

Requires Docker and `make`.

```bash
cp .env.example .env   # optional - fill in GEMINI_API_KEY if you want team-radio classification
make
```

This runs, in order:
1. Backend test suite (pytest) and frontend test suite (vitest), each gated
   on **>=95% coverage** — the build stops here if either fails.
2. `docker compose build` for the backend and frontend images.
3. `docker compose up`, which starts, in dependency order:
   - `db` — Postgres 17, with a named volume (`pgdata`) so your data survives
     `docker compose down`, container recreation, and image rebuilds. It's
     only deleted by an explicit `make clean` (`docker compose down -v`).
   - `migrate` — applies `backend/migrations/*.sql`, then exits.
   - `backend` — FastAPI on **http://localhost:8000**.
   - `frontend` — the built dashboard on **http://localhost:5173**.

Other targets: `make test` (just the test/coverage gate), `make build` (test
+ build images, no run), `make down` (stop, keep data), `make clean` (stop
and delete the Postgres volume), `make logs` (tail all service logs).

## Local development (without Docker)

See `backend/README.md`-equivalent setup: `uv sync` then
`uv run uvicorn main:app --reload` for the API, and `npm install && npm run
dev` in `frontend/` for the Vite dev server with hot reload. You'll need a
local Postgres instance either way — `backend/config/database_config.py`
reads `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_PASSWORD` from the
environment.

## Team radio transcription

The backend image bakes in the Whisper model (`ggml-small.bin`, ~487MB,
downloaded at build time from whisper.cpp's own model host) used to
transcribe team radio clips, so it works out of the box — no separate
download or volume mount needed. This is also why the backend build takes a
while and the image is fairly large. Classifying transcripts as
driver/pit-wall and flagging notable messages (box calls, incidents, etc.)
is a separate step that needs `GEMINI_API_KEY` set - see `.env.example`.

---

*Unofficial, fan-built project. Not affiliated with or endorsed by Formula 1,
FOM, or FIA.*
