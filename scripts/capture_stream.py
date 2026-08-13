"""
Standalone F1 live-timing raw capture process.

Deliberately independent of the FastAPI/uvicorn backend's process lifecycle: this
script's only job is to keep stream_logs/live_<session-name>.jsonl growing for as
long as a session is live, no matter what happens to the backend or frontend
(restarts, crashes, redeploys, a developer iterating on frontend code). The backend
attaches to the same file by tailing it (see utils/live_tail.py) instead of owning
the SignalR connection itself, so restarting the backend never interrupts capture.

Run once per session and leave it running throughout - typically via the watchdog
wrapper (scripts/run_capture.sh), which also restarts this script if the process
itself ever dies (OOM, a hard crash), on top of the self-healing reconnect loop
already built into F1SignalRStreamer.run() for ordinary SignalR disconnects.

Usage:
    uv run python -m scripts.capture_stream --session-name quali_2026_07_25
    uv run python -m scripts.capture_stream --session-name quali_2026_07_25 --token <f1tv-token>

If --token is omitted, falls back to a saved F1TV token (utils.f1_auth.get_saved_token)
if valid, otherwise proceeds unauthenticated - exactly like /start-live-stream. Live
timing data itself doesn't require authentication (only team-radio audio downloads do,
and this script doesn't download audio at all - see utils/raw_capture.py).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import threading
from pathlib import Path
from typing import Optional

from utils import f1_auth
from utils.live_stream import STREAM_LOGS_DIR, F1SignalRStreamer
from utils.raw_capture import RawStreamArchiver

logger = logging.getLogger(__name__)


def _resolve_token(explicit_token: Optional[str]) -> str:
    if explicit_token:
        return explicit_token
    saved = f1_auth.get_saved_token()
    if saved and f1_auth.validate_subscription_token(saved):
        logger.info("Using saved F1TV subscription token")
        return saved
    logger.info("No token available - capturing unauthenticated (live timing data doesn't require it)")
    return ""


def log_path_for_session(session_name: str) -> Path:
    return STREAM_LOGS_DIR / f"live_{session_name}.jsonl"


def run_capture(session_name: str, token: Optional[str] = None) -> None:  # pragma: no cover - real threads/signal handlers/infinite loop; unsafe to run inside a test process
    """Blocks forever (until SIGINT/SIGTERM), keeping the archiver's SignalR connection
    alive via F1SignalRStreamer's self-healing reconnect loop."""
    STREAM_LOGS_DIR.mkdir(exist_ok=True)
    log_path = log_path_for_session(session_name)
    archiver = RawStreamArchiver(log_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    streamer = F1SignalRStreamer(
        access_token=_resolve_token(token),
        loop=loop,
        sink=archiver,
        stream_id=f"live_{session_name}",
    )

    stream_thread = threading.Thread(target=streamer.run, daemon=False, name="f1-capture-stream")

    def _shutdown(*_args: object) -> None:
        logger.info("Shutdown signal received - stopping capture")
        streamer.stop()
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Starting capture for session=%s -> %s", session_name, log_path)
    stream_thread.start()
    try:
        loop.run_forever()  # keeps a live loop for run_coroutine_threadsafe to land on
    finally:
        stream_thread.join(timeout=10)
        archiver.close()
        logger.info("Capture stopped for session=%s", session_name)


def main() -> None:  # pragma: no cover - thin CLI entrypoint, delegates straight to run_capture
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session-name", required=True, help="Stable name identifying this session, e.g. quali_2026_07_25")
    parser.add_argument("--token", default=None, help="F1TV access token (optional - falls back to saved token, then unauthenticated)")
    args = parser.parse_args()

    run_capture(session_name=args.session_name, token=args.token)


if __name__ == "__main__":  # pragma: no cover - script entrypoint guard
    main()
