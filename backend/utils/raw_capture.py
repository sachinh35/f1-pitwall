"""
Archive-only sink for utils/live_stream.py's F1SignalRStreamer - satisfies StreamSink
without any of LiveSessionPipeline's dependencies (Postgres, session-state decode, SSE
broadcast). This is what scripts/capture_stream.py uses: its only job is to keep raw
JSONL capture running for as long as a session is live, independent of the FastAPI
backend's process lifecycle, so it must not depend on anything that could make it crash
(a DB outage, a decode bug in a new message shape, etc.).

Writes the exact same line format LiveSessionPipeline._archive_raw/log_event produce, so
utils/replay.py's iter_log_messages (and utils/live_tail.py) parse it unchanged - the
capture process and the backend agree on one file format without sharing code that could
introduce backend-only dependencies into the capture process.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TextIO

logger = logging.getLogger(__name__)


class RawStreamArchiver:
    """Appends every message/log event to a jsonl file, flushed on every write.

    Flushing per-write (rather than LiveSessionPipeline's batch-of-50) is deliberate: this
    file is now the sole durable record of the session - unlike the backend-owned pipeline,
    there's no in-memory SessionState or SSE-connected frontend also holding the data, so a
    crash between writes must lose at most one message, not up to 49. The F1 control-plane
    feed this captures is a few messages a second at most, so the extra I/O is immaterial.
    """

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = open(log_path, "a", encoding="utf-8")

    def _write(self, entry: dict) -> None:
        self._file.write(json.dumps(entry, default=str) + "\n")
        self._file.flush()

    def log_event(self, event_type: str, data: Any) -> None:
        self._write({
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data,
        })

    async def handle_message(self, event_name: str, payload: Any, event_time: Optional[datetime] = None) -> None:
        """Archive one raw message. Async only to satisfy StreamSink - the work itself
        (a file write) is synchronous and fast enough not to need offloading. event_time is
        unused here - this sink always records its own capture timestamp (the whole point
        of the raw archive is to be the source of truth for "when did this really happen",
        so it doesn't need to be told)."""
        self._write({
            "timestamp": datetime.now().isoformat(),
            "event_type": "message",
            "data": {"event_name": event_name, "payload": payload},
        })

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
