"""Unit tests for scripts/capture_stream.py's pure logic - token resolution and log
path construction. run_capture()/main() are excluded from coverage (pragma: no cover)
since they start real threads, register process-wide signal handlers, and block
forever - not safely runnable inside a test process."""
from unittest.mock import patch

from scripts import capture_stream


def test_resolve_token_prefers_explicit_token() -> None:
    with patch.object(capture_stream.f1_auth, "get_saved_token") as mock_get_saved:
        result = capture_stream._resolve_token("explicit-token")
    assert result == "explicit-token"
    mock_get_saved.assert_not_called()


def test_resolve_token_falls_back_to_valid_saved_token() -> None:
    with patch.object(capture_stream.f1_auth, "get_saved_token", return_value="saved-token"), \
         patch.object(capture_stream.f1_auth, "validate_subscription_token", return_value=True):
        result = capture_stream._resolve_token(None)
    assert result == "saved-token"


def test_resolve_token_falls_back_to_unauthenticated_when_no_valid_saved_token() -> None:
    with patch.object(capture_stream.f1_auth, "get_saved_token", return_value=None), \
         patch.object(capture_stream.f1_auth, "validate_subscription_token", return_value=False):
        result = capture_stream._resolve_token(None)
    assert result == ""


def test_resolve_token_falls_back_to_unauthenticated_when_saved_token_invalid() -> None:
    with patch.object(capture_stream.f1_auth, "get_saved_token", return_value="expired-token"), \
         patch.object(capture_stream.f1_auth, "validate_subscription_token", return_value=False):
        result = capture_stream._resolve_token(None)
    assert result == ""


def test_log_path_for_session() -> None:
    path = capture_stream.log_path_for_session("quali_2026_07_25")
    assert path == capture_stream.STREAM_LOGS_DIR / "live_quali_2026_07_25.jsonl"
