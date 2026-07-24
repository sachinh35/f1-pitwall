FROM python:3.14-slim

# pywhispercpp compiles whisper.cpp (C++) from source at install time - a
# fresh slim image has no compiler toolchain by default, unlike a dev Mac
# with Xcode command line tools already installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# The official static uv binary - no separate Python bootstrap needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependency manifests first, so `uv sync` is cached separately from app code
# changes - editing main.py shouldn't force a pywhispercpp recompile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# The local Whisper model (~487MB) is intentionally NOT baked into this image -
# mount it at runtime, e.g.:
#   docker run -v ~/.cache/openwhispr/whisper-models:/models \
#              -e WHISPER_MODELS_DIR=/models ...
# See utils/whisper_transcriber.py.

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
