---
title: F1 Pit Wall
---

**F1 Pit Wall** is a live F1 race dashboard - timing tower, race control feed,
team radio, and car telemetry, pit-wall style. It streams F1's live timing
feed (or replays a captured session) over Server-Sent Events into a React
dashboard, backed by PostgreSQL for historical queries.

*Unofficial, fan-built project. Not affiliated with or endorsed by Formula 1,
FOM, or FIA.*

## Repository layout

- `backend/` - FastAPI + PostgreSQL (asyncpg), live-timing ingestion and REST API.
- `frontend/` - React + Vite + MUI dashboard.

Each half keeps its own `package.json`/`pyproject.toml` and can be deployed
independently in production (e.g. frontend on Vercel, backend on Render/Fly).
The repo is a single monorepo so anyone can clone once and run the whole
stack locally - see [Setup](setup.html).

## Where to go next

- **[Architecture](architecture.html)** - how the pieces fit together: the live-timing
  pipeline, persistence, and the Docker Compose stack.
- **[Setup](setup.html)** - clone-and-run quickstart (Docker), local dev without
  Docker, and the environment variables you can configure.
- **[Troubleshooting](troubleshooting.html)** - real gotchas encountered running this,
  and how they were fixed.

## Quickstart

```bash
git clone https://github.com/sachinh35/f1-pitwall.git
cd f1-pitwall
cp .env.example .env   # optional - fill in GEMINI_API_KEY for team-radio classification
make
```

Frontend: `http://localhost:5173` · Backend: `http://localhost:8000`

## License

[MIT](https://github.com/sachinh35/f1-pitwall/blob/main/LICENSE)
