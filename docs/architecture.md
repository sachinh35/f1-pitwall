---
title: Architecture
---

## Live-timing pipeline

F1's live timing data arrives over a SignalR feed (real sessions) or is
replayed from a captured `stream_logs/*.jsonl` file (simulations) - both
paths are driven through the exact same pipeline in
`backend/utils/live_session_pipeline.py`:

1. **Archive** - every raw message is appended to a `stream_logs/*.jsonl`
   file as it arrives, regardless of source, so any live session can later
   be replayed identically.
2. **Decode + merge** - the raw payload is decoded (some topics, like
   `CarData.z`/`Position.z`, arrive base64+raw-deflate-compressed) and
   merged into an in-memory reducer, `SessionState`
   (`backend/utils/session_state.py`).
3. **Broadcast** - the resulting state diff is shaped into a JSON payload
   (`diff_to_wire`) and pushed to every subscriber over Server-Sent Events.
   A new subscriber connecting mid-session gets a full `snapshot()` of
   current state first, then live diffs after that.
4. **Persist** - detached background tasks write durable data (laps, stints,
   race control events, team radio, telemetry) to PostgreSQL, off the hot
   broadcast path, so a slow write never blocks live delivery.

The frontend connects to `GET /live/{stream_id}/events` and consumes this
as a single SSE stream, reconstructing race state client-side.

## Team radio pipeline

Each team-radio message triggers a separate, detached pipeline
(`utils/team_radio_pipeline.py`): download the clip's audio from F1's static
CDN, transcribe it locally with Whisper (`pywhispercpp`), and optionally
classify the transcript (driver vs. pit-wall, "notable" or not) via a Gemini
model, if `GEMINI_API_KEY` is configured. Every stage broadcasts its own SSE
update as it completes, so the UI can show "downloading -> transcribing ->
done" progressively rather than waiting for the whole pipeline.

## Persistence

PostgreSQL (via `asyncpg`) is the single source of truth for everything
except the raw capture files. Schema changes are plain, numbered SQL files
under `backend/migrations/`, applied by a small custom runner
(`backend/scripts/migrate.py`) that tracks what's been applied in a
`schema_migrations` table - no ORM migration framework, since the schema is
small enough that this is simpler to reason about.

## Monorepo layout

`backend/` and `frontend/` are two independently-deployable projects (each
keeps its own `pyproject.toml`/`package.json`) merged into one repo via
`git subtree`, preserving each side's full original commit history. This
means:

- You can `git clone` this one repo and get both halves, with real history
  intact (`git blame`/`git log -- backend/main.py` work as normal).
- Each half can still be deployed independently in production (e.g. a
  hosting platform pointed at the `frontend/` or `backend/` subdirectory as
  its build root) - the monorepo structure doesn't force a combined deploy.

## The Docker Compose stack

`docker-compose.yml` defines four services:

| Service    | What it is                                                    | Persists          |
|------------|----------------------------------------------------------------|--------------------|
| `db`       | Postgres 17                                                     | named volume `pgdata` |
| `migrate`  | one-shot: applies `migrations/*.sql`, then exits                | -                  |
| `backend`  | FastAPI on `:8000`, Whisper model baked into the image at build time | `stream_logs/`, `audio_cache/`, F1TV auth token - all bind-mounted to the host |
| `frontend` | the built React app served by nginx on `:5173`                  | -                  |

Startup order is enforced with `depends_on`: `db` (healthy) -> `migrate`
(completes successfully) -> `backend` -> `frontend`.

`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME`/`DB_PASSWORD` are all overridable via
`.env`, so `migrate`/`backend` can be pointed at a Postgres you already have
running natively (e.g. `DB_HOST=host.docker.internal`) instead of the
compose-managed `db` service - see [Setup](setup.html).
