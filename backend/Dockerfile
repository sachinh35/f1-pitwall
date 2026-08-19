FROM python:3.14-slim

# pywhispercpp compiles whisper.cpp (C++) from source at install time - a
# fresh slim image has no compiler toolchain by default, unlike a dev Mac
# with Xcode command line tools already installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Bake in the same Whisper model used for local dev (ggml-small.bin, ~487MB) from
# whisper.cpp's own official model host, so team-radio transcription works out of
# the box with no runtime volume mount needed. See team_radio/whisper_transcriber.py -
# WHISPER_MODELS_DIR points it at this directory instead of the local-dev default
# (~/.cache/openwhispr/whisper-models). Done early, independent of app code, so it
# isn't re-downloaded on every source change.
ENV WHISPER_MODELS_DIR=/models
RUN mkdir -p /models && \
    curl -fL --retry 3 -o /models/ggml-small.bin \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin

# The official static uv binary - no separate Python bootstrap needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependency manifests first, so `uv sync` is cached separately from app code
# changes - editing main.py shouldn't force a pywhispercpp recompile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
