"""
Unit tests for the F1TV token-status endpoints (GET /f1tv-token/status, POST
/f1tv-token) and the token-validation gate on POST /start-live-stream.

Uses FastAPI's TestClient without entering it as a context manager, so the
app's startup event (DatabaseManager.get_pool(), which needs a real Postgres) is
never triggered - none of these endpoints touch the database. f1_auth is mocked
at the module level (main.f1_auth), matching how live/live_session_pipeline.py's
tests mock f1_auth.validate_subscription_token.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from auth.f1_auth import TokenValidity

client = TestClient(main.app)

_VALID = TokenValidity(valid=True, reason=None, expires_at="2027-01-01T00:00:00+00:00")
_EXPIRED = TokenValidity(valid=False, reason="Token has expired", expires_at="2025-12-10T00:00:00+00:00")
_MISSING = TokenValidity(valid=False, reason="No F1TV token configured", expires_at=None)


# ---- GET /f1tv-token/status ----

def test_token_status_valid() -> None:
    with patch.object(main.f1_auth, "get_saved_token", return_value="some.jwt.token"), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_VALID) as mock_describe:
        response = client.get("/f1tv-token/status")

    assert response.status_code == 200
    assert response.json() == {"valid": True, "reason": None, "expires_at": "2027-01-01T00:00:00+00:00"}
    mock_describe.assert_called_once_with("some.jwt.token")


def test_token_status_expired() -> None:
    with patch.object(main.f1_auth, "get_saved_token", return_value="expired.jwt.token"), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_EXPIRED):
        response = client.get("/f1tv-token/status")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "Token has expired"


def test_token_status_no_saved_token() -> None:
    with patch.object(main.f1_auth, "get_saved_token", return_value=None), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_MISSING):
        response = client.get("/f1tv-token/status")

    assert response.status_code == 200
    assert response.json() == {"valid": False, "reason": "No F1TV token configured", "expires_at": None}


# ---- POST /f1tv-token ----

def test_update_token_valid_saves_it() -> None:
    with patch.object(main.f1_auth, "describe_token_validity", return_value=_VALID) as mock_describe, \
         patch.object(main.f1_auth, "save_token") as mock_save:
        response = client.post("/f1tv-token", json={"token": "fresh.jwt.token"})

    assert response.status_code == 200
    assert response.json()["valid"] is True
    mock_describe.assert_called_once_with("fresh.jwt.token")
    mock_save.assert_called_once_with("fresh.jwt.token")


def test_update_token_invalid_does_not_save() -> None:
    with patch.object(main.f1_auth, "describe_token_validity", return_value=_EXPIRED), \
         patch.object(main.f1_auth, "save_token") as mock_save:
        response = client.post("/f1tv-token", json={"token": "bad.jwt.token"})

    # Intentionally 200, not an error status - "checked and it's invalid" is a
    # normal outcome the frontend renders, not a server error.
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "Token has expired"
    mock_save.assert_not_called()


# ---- POST /start-live-stream token gate ----

def test_start_live_stream_401s_with_no_valid_saved_token() -> None:
    with patch.object(main.f1_auth, "get_saved_token", return_value=None), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_MISSING):
        response = client.post("/start-live-stream", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "No F1TV token configured"


def test_start_live_stream_401s_with_expired_saved_token() -> None:
    with patch.object(main.f1_auth, "get_saved_token", return_value="expired.jwt.token"), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_EXPIRED):
        response = client.post("/start-live-stream", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


def test_start_live_stream_proceeds_with_valid_saved_token() -> None:
    fake_streamer = type(
        "FakeStreamer",
        (),
        {"get_stream_info": lambda self: {"stream_id": "abc123", "log_file": "stream_logs/abc123.jsonl"}},
    )()

    with patch.object(main.f1_auth, "get_saved_token", return_value="good.jwt.token"), \
         patch.object(main.f1_auth, "describe_token_validity", return_value=_VALID), \
         patch.object(main.live_stream, "start_stream", return_value=fake_streamer) as mock_start:
        response = client.post("/start-live-stream", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["stream_id"] == "abc123"
    mock_start.assert_called_once()
    assert mock_start.call_args.kwargs["access_token"] == "good.jwt.token"


def test_start_live_stream_skips_saved_token_lookup_when_explicit_token_given() -> None:
    """The new gate only applies to the no-explicit-token branch - an explicitly
    provided access_token must not be re-checked against describe_token_validity."""
    fake_streamer = type(
        "FakeStreamer",
        (),
        {"get_stream_info": lambda self: {"stream_id": "xyz789", "log_file": "stream_logs/xyz789.jsonl"}},
    )()

    with patch.object(main.f1_auth, "describe_token_validity") as mock_describe, \
         patch.object(main.live_stream, "start_stream", return_value=fake_streamer) as mock_start:
        response = client.post("/start-live-stream", json={"access_token": "explicit.jwt.token"})

    assert response.status_code == 200
    mock_describe.assert_not_called()
    assert mock_start.call_args.kwargs["access_token"] == "explicit.jwt.token"
