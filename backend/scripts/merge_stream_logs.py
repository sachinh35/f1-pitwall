"""
Merge stream_logs/*.jsonl raw-capture files that belong to the same real F1 session
into one chronologically-ordered file.

Necessary because every /start-live-stream call (each backend restart, each new
browser-driven connection) opens a brand-new f1_stream_<timestamp>.jsonl file (see
live/live_stream.py's F1SignalRStreamer._log_file_path) - a session watched across
several restarts ends up fragmented across several files instead of one continuous
record. This stitches them back together after the fact; it doesn't change how the
live capture itself writes files.

Usage:
    uv run python -m scripts.merge_stream_logs <session_key> [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

STREAM_LOGS_DIR = Path(__file__).resolve().parent.parent / "stream_logs"


def session_key_of(path: Path) -> Optional[int]:
    """The real F1 session_key this capture file belongs to, read from its SessionInfo
    message's payload - None if the file has no SessionInfo line (e.g. empty, or a
    connection that dropped before SessionInfo ever arrived)."""
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                data = obj.get("data", {})
                if data.get("event_name") == "SessionInfo":
                    return data.get("payload", {}).get("Key")
    except (OSError, json.JSONDecodeError):
        return None
    return None


def find_files_for_session(session_key: int, stream_logs_dir: Path = STREAM_LOGS_DIR) -> List[Path]:
    """Every stream_logs/*.jsonl file whose SessionInfo message reports this session_key,
    in filename order (not yet the final chronological order - see merge_files)."""
    return [
        path
        for path in sorted(stream_logs_dir.glob("f1_stream_*.jsonl"))
        if session_key_of(path) == session_key
    ]


def merge_files(files: List[Path], out_path: Path) -> int:
    """
    Concatenate every line from every file, sorted by each line's own `timestamp`
    field - not by file order - since two connections to the same session can overlap
    in real time (e.g. one kept running while a second was started alongside it), so
    one file's lines don't all necessarily precede the other's. Returns the number of
    lines written.
    """
    lines_with_ts = []
    for path in files:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                lines_with_ts.append((obj.get("timestamp", ""), line))

    lines_with_ts.sort(key=lambda pair: pair[0])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for _, line in lines_with_ts:
            f.write(line + "\n")
    return len(lines_with_ts)


def _main() -> None:  # pragma: no cover - thin CLI entrypoint (argparse plumbing only); find_files_for_session/merge_files are tested directly
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_key", type=int)
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Output path (default: stream_logs/f1_stream_session_<session_key>_merged.jsonl)",
    )
    args = parser.parse_args()

    out_path = args.out or STREAM_LOGS_DIR / f"f1_stream_session_{args.session_key}_merged.jsonl"

    files = find_files_for_session(args.session_key)
    if not files:
        logger.warning("No stream_logs files found for session_key=%s", args.session_key)
        return

    logger.info("Merging %d files for session_key=%s: %s", len(files), args.session_key, [p.name for p in files])
    count = merge_files(files, out_path)
    logger.info("Wrote %d lines to %s", count, out_path)


if __name__ == "__main__":  # pragma: no cover - script entrypoint guard
    _main()
