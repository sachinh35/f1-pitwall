"""
Local Whisper transcription via pywhispercpp (GGML/whisper.cpp), using the
model already cached on disk at `~/.cache/openwhispr/whisper-models` rather
than downloading model weights ourselves.

pywhispercpp's `Model` takes a model *name* plus a directory to find it in
(`Model(model="small", models_dir=...)`), not a direct path to the .bin file -
confirmed by inspecting the installed package's real signature and by running
a real transcription against it, rather than assumed from its docs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME: str = "small"
# Overridable via WHISPER_MODELS_DIR - the default assumes local dev on a
# machine where the OpenWhispr app already downloaded a model. A container
# has no such directory unless one is volume-mounted and this is pointed at it.
DEFAULT_MODELS_DIR: Path = Path(
    os.getenv("WHISPER_MODELS_DIR", str(Path.home() / ".cache" / "openwhispr" / "whisper-models"))
)

# Whisper transcription is CPU/GPU-bound; running it inline would block the
# asyncio event loop that's simultaneously processing live timing messages.
# A single worker is enough - team radio produces on the order of tens of
# clips per race (29 in the captured Qatar race), nowhere near enough volume
# to need more, and each clip transcribes in ~2s on Metal.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")

_model_cache: dict[tuple[str, str], "object"] = {}


def _load_model(model_name: str, models_dir: Path) -> object:
    """Load (or return the cached) Whisper model. Loading takes several seconds, so it's done once and reused."""
    cache_key = (model_name, str(models_dir))
    if cache_key not in _model_cache:
        # Imported lazily so importing this module doesn't require pywhispercpp's
        # native extension to be loadable in contexts that never transcribe anything.
        from pywhispercpp.model import Model

        model_file = models_dir / f"ggml-{model_name}.bin"
        if not model_file.exists():
            raise FileNotFoundError(f"Whisper model file not found: {model_file}")

        logger.info("Loading Whisper model '%s' from %s", model_name, models_dir)
        _model_cache[cache_key] = Model(model=model_name, models_dir=str(models_dir))

    return _model_cache[cache_key]


def _transcribe_sync(audio_path: Path, model_name: str, models_dir: Path) -> str:
    model = _load_model(model_name, models_dir)
    segments = model.transcribe(str(audio_path))
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe(
    audio_path: Path,
    model_name: str = DEFAULT_MODEL_NAME,
    models_dir: Path = DEFAULT_MODELS_DIR,
) -> str:
    """
    Transcribe an audio file to text using the local GGML Whisper model.

    Runs on a dedicated single-worker thread pool so it never blocks the
    asyncio event loop handling live timing messages concurrently.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, _transcribe_sync, audio_path, model_name, models_dir)
