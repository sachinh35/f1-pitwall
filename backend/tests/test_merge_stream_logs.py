"""Unit tests for scripts/merge_stream_logs.py's file-discovery/merge logic."""
import json
from pathlib import Path

from scripts.merge_stream_logs import find_files_for_session, merge_files, session_key_of


def _write_jsonl(path: Path, lines: list) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _session_info_line(timestamp: str, session_key: int) -> dict:
    return {
        "timestamp": timestamp,
        "data": {"event_name": "SessionInfo", "payload": {"Key": session_key}},
    }


def test_session_key_of_reads_from_session_info_message(tmp_path: Path) -> None:
    path = tmp_path / "f1_stream_1.jsonl"
    _write_jsonl(path, [_session_info_line("2026-01-01T00:00:00", 42)])

    assert session_key_of(path) == 42


def test_session_key_of_none_when_no_session_info(tmp_path: Path) -> None:
    path = tmp_path / "f1_stream_1.jsonl"
    _write_jsonl(path, [{"timestamp": "2026-01-01T00:00:00", "data": {"event_name": "Heartbeat", "payload": {}}}])

    assert session_key_of(path) is None


def test_session_key_of_none_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "f1_stream_empty.jsonl"
    path.write_text("")

    assert session_key_of(path) is None


def test_session_key_of_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "f1_stream_1.jsonl"
    path.write_text("\n\n" + json.dumps(_session_info_line("2026-01-01T00:00:00", 42).copy()) + "\n")

    assert session_key_of(path) == 42


def test_session_key_of_none_for_malformed_json_line(tmp_path: Path) -> None:
    path = tmp_path / "f1_stream_1.jsonl"
    path.write_text("{not valid json\n")

    assert session_key_of(path) is None


def test_find_files_for_session_filters_by_session_key(tmp_path: Path) -> None:
    match_a = tmp_path / "f1_stream_1.jsonl"
    match_b = tmp_path / "f1_stream_2.jsonl"
    other = tmp_path / "f1_stream_3.jsonl"
    _write_jsonl(match_a, [_session_info_line("2026-01-01T00:00:00", 42)])
    _write_jsonl(match_b, [_session_info_line("2026-01-01T00:05:00", 42)])
    _write_jsonl(other, [_session_info_line("2026-01-01T00:00:00", 99)])

    result = find_files_for_session(42, stream_logs_dir=tmp_path)

    assert sorted(p.name for p in result) == ["f1_stream_1.jsonl", "f1_stream_2.jsonl"]


def test_merge_files_interleaves_by_timestamp_not_file_order(tmp_path: Path) -> None:
    # File B's lines are earlier in real time than some of file A's, despite A being
    # passed first - the merge must sort by each line's own timestamp, not concatenate
    # file-by-file, since two connections to the same session can overlap.
    file_a = tmp_path / "f1_stream_a.jsonl"
    file_b = tmp_path / "f1_stream_b.jsonl"
    _write_jsonl(file_a, [
        {"timestamp": "2026-01-01T00:00:02", "data": {"event_name": "Heartbeat", "payload": {"n": 2}}},
        {"timestamp": "2026-01-01T00:00:04", "data": {"event_name": "Heartbeat", "payload": {"n": 4}}},
    ])
    _write_jsonl(file_b, [
        {"timestamp": "2026-01-01T00:00:01", "data": {"event_name": "Heartbeat", "payload": {"n": 1}}},
        {"timestamp": "2026-01-01T00:00:03", "data": {"event_name": "Heartbeat", "payload": {"n": 3}}},
    ])
    out_path = tmp_path / "merged.jsonl"

    count = merge_files([file_a, file_b], out_path)

    assert count == 4
    written = [json.loads(line)["data"]["payload"]["n"] for line in out_path.read_text().splitlines()]
    assert written == [1, 2, 3, 4]


def test_merge_files_skips_blank_lines(tmp_path: Path) -> None:
    file_a = tmp_path / "f1_stream_a.jsonl"
    file_a.write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:01", "data": {"event_name": "Heartbeat", "payload": {}}})
        + "\n\n"
    )
    out_path = tmp_path / "merged.jsonl"

    count = merge_files([file_a], out_path)

    assert count == 1


def test_merge_files_creates_output_parent_directory(tmp_path: Path) -> None:
    file_a = tmp_path / "f1_stream_a.jsonl"
    _write_jsonl(file_a, [_session_info_line("2026-01-01T00:00:00", 42)])
    out_path = tmp_path / "nested" / "merged.jsonl"

    merge_files([file_a], out_path)

    assert out_path.exists()
