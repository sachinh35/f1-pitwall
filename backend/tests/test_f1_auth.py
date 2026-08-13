"""
Unit tests for utils/f1_auth.py's browser-based auth flow (ported from FastF1's
fastf1/internals/f1auth.py - see ATTRIBUTION.md). Real JWKS/network verification is
always mocked (validate_subscription_token) - these tests never call F1's real API,
and the real ~/.local/share/f1-dashboard/f1auth.json is never touched (AUTH_DATA_FILE
is monkeypatched to a tmp_path).
"""
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from utils import f1_auth


@pytest.fixture(autouse=True)
def _isolate_browser_auth_state(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Every test starts with a clean slate: no in-flight flow, and AUTH_DATA_FILE
    pointed at a throwaway path so a test can never read or clobber a developer's
    real saved F1TV token."""
    monkeypatch.setattr(f1_auth, "_browser_auth_state", None)
    monkeypatch.setattr(f1_auth, "AUTH_DATA_FILE", tmp_path / "f1auth.json")
    yield
    # Clean up any server a test left running (e.g. on assertion failure mid-test).
    if f1_auth._browser_auth_state is not None:
        f1_auth._browser_auth_state["httpd"].shutdown()
        f1_auth._browser_auth_state["httpd"].server_close()
        f1_auth._browser_auth_state = None


def _login_session_body(subscription_token: str) -> bytes:
    """Builds the exact payload shape f1login.fastf1.dev POSTs: {"loginSession": "<url-encoded JSON>"}."""
    inner = urllib.parse.quote(json.dumps({"data": {"subscriptionToken": subscription_token}}))
    return json.dumps({"loginSession": inner}).encode("utf-8")


# ---- _parse_login_session_payload ----

def test_parse_login_session_payload_extracts_token() -> None:
    body = _login_session_body("real.jwt.token")
    assert f1_auth._parse_login_session_payload(body) == "real.jwt.token"


def test_parse_login_session_payload_returns_none_for_malformed_json() -> None:
    assert f1_auth._parse_login_session_payload(b"not json at all") is None


def test_parse_login_session_payload_returns_none_when_login_session_key_missing() -> None:
    assert f1_auth._parse_login_session_payload(json.dumps({"other": "field"}).encode()) is None


def test_parse_login_session_payload_returns_none_when_subscription_token_missing() -> None:
    inner = urllib.parse.quote(json.dumps({"data": {}}))
    body = json.dumps({"loginSession": inner}).encode()
    assert f1_auth._parse_login_session_payload(body) is None


# ---- start_browser_auth_flow / check_browser_auth_status ----

def test_check_status_before_any_flow_started() -> None:
    assert f1_auth.check_browser_auth_status() == {"status": "not_started"}


def test_start_browser_auth_flow_returns_relay_url_with_port() -> None:
    auth_url = f1_auth.start_browser_auth_flow()
    assert re.match(r"^https://f1login\.fastf1\.dev\?port=\d+$", auth_url)


def test_status_is_pending_before_the_callback_lands() -> None:
    auth_url = f1_auth.start_browser_auth_flow()
    status = f1_auth.check_browser_auth_status()
    assert status == {"status": "pending", "auth_url": auth_url}


def test_full_flow_real_local_http_callback_marks_authenticated_and_saves_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercises the actual local HTTPServer over a real socket - not mocked - since that's
    the part worth genuinely proving works (parsing/threading is covered elsewhere)."""
    monkeypatch.setattr(f1_auth, "validate_subscription_token", lambda token: True)

    auth_url = f1_auth.start_browser_auth_flow()
    port = int(auth_url.rsplit("=", 1)[1])

    response = httpx.post(
        f"http://127.0.0.1:{port}/auth",
        content=_login_session_body("captured.subscription.token"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200

    status = f1_auth.check_browser_auth_status()
    assert status == {"status": "authenticated"}
    assert f1_auth.AUTH_DATA_FILE.read_text() == "captured.subscription.token"
    # The server must be shut down and cleared once terminal, not left holding the port open.
    assert f1_auth._browser_auth_state is None


def test_full_flow_invalid_token_marks_failed_and_does_not_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f1_auth, "validate_subscription_token", lambda token: False)

    auth_url = f1_auth.start_browser_auth_flow()
    port = int(auth_url.rsplit("=", 1)[1])

    httpx.post(
        f"http://127.0.0.1:{port}/auth",
        content=_login_session_body("bad.token"),
        headers={"Content-Type": "application/json"},
    )

    status = f1_auth.check_browser_auth_status()
    assert status["status"] == "failed"
    assert "error" in status
    assert not f1_auth.AUTH_DATA_FILE.exists()


# ---- describe_token_validity / validate_subscription_token / save_token ----
#
# A real RSA keypair is generated once per test module and used to sign genuine
# RS256 tokens - _get_jwk_from_jwks_uri's HTTP call (requests.get) is mocked to
# serve this keypair's public half as the JWKS, so the actual verification path
# (jwt.decode + RSAAlgorithm) is exercised for real, not just the wrapper.

_TEST_KID = "test-kid"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _mock_jwks(monkeypatch: pytest.MonkeyPatch, rsa_keypair):
    """Serves rsa_keypair's public key as the JWKS response for every test in this
    module, in place of a real network call to F1's JWKS_URL."""
    _, public_key = rsa_keypair
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = _TEST_KID

    class _FakeJwksResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"keys": [jwk]}

    monkeypatch.setattr(f1_auth.requests, "get", lambda *_args, **_kwargs: _FakeJwksResponse())
    yield


def _make_token(rsa_keypair, exp_delta: timedelta, kid: str = _TEST_KID) -> str:
    private_key, _ = rsa_keypair
    payload = {"exp": datetime.now(tz=timezone.utc) + exp_delta}
    return jwt.encode(payload, key=private_key, algorithm="RS256", headers={"kid": kid})


def test_describe_token_validity_valid_token(rsa_keypair) -> None:
    token = _make_token(rsa_keypair, timedelta(hours=1))
    result = f1_auth.describe_token_validity(token)
    assert result.valid is True
    assert result.reason is None
    assert result.expires_at is not None


def test_describe_token_validity_expired_token(rsa_keypair) -> None:
    token = _make_token(rsa_keypair, timedelta(hours=-1))
    result = f1_auth.describe_token_validity(token)
    assert result.valid is False
    assert result.reason == "Token has expired"
    # Expiry is still reported for display, read unverified from the payload.
    assert result.expires_at is not None


def test_describe_token_validity_malformed_token() -> None:
    result = f1_auth.describe_token_validity("not-a-jwt-at-all")
    assert result.valid is False
    assert result.reason is not None
    assert "invalid" in result.reason.lower()
    assert result.expires_at is None


def test_describe_token_validity_no_token() -> None:
    assert f1_auth.describe_token_validity(None) == f1_auth.TokenValidity(
        valid=False, reason="No F1TV token configured", expires_at=None
    )
    assert f1_auth.describe_token_validity("") == f1_auth.TokenValidity(
        valid=False, reason="No F1TV token configured", expires_at=None
    )


def test_describe_token_validity_bad_signature() -> None:
    """A token signed by a different key than the one JWKS actually serves for that
    kid - simulates a forged/corrupted token."""
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {"exp": datetime.now(tz=timezone.utc) + timedelta(hours=1)}
    token = jwt.encode(payload, key=other_private_key, algorithm="RS256", headers={"kid": _TEST_KID})
    result = f1_auth.describe_token_validity(token)
    assert result.valid is False
    assert result.reason is not None and "invalid" in result.reason.lower()


def test_describe_token_validity_missing_kid(rsa_keypair) -> None:
    private_key, _ = rsa_keypair
    payload = {"exp": datetime.now(tz=timezone.utc) + timedelta(hours=1)}
    token = jwt.encode(payload, key=private_key, algorithm="RS256")
    result = f1_auth.describe_token_validity(token)
    assert result.valid is False
    assert result.reason == "Token is invalid: missing key id"


@pytest.mark.parametrize("exp_delta", [timedelta(hours=1), timedelta(hours=-1)])
def test_validate_subscription_token_matches_describe_token_validity(rsa_keypair, exp_delta) -> None:
    """Regression: validate_subscription_token's plain bool must keep agreeing with
    describe_token_validity().valid post-refactor, for both a valid and an expired token."""
    token = _make_token(rsa_keypair, exp_delta)
    assert f1_auth.validate_subscription_token(token) == f1_auth.describe_token_validity(token).valid


def test_validate_subscription_token_false_for_malformed_token() -> None:
    assert f1_auth.validate_subscription_token("garbage") is False


def test_save_token_writes_stripped_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    auth_file = tmp_path / "nested" / "f1auth.json"
    monkeypatch.setattr(f1_auth, "AUTH_DATA_FILE", auth_file)

    f1_auth.save_token("  some.raw.jwt  \n")

    assert auth_file.read_text() == "some.raw.jwt"


def test_save_token_overwrites_existing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    auth_file = tmp_path / "f1auth.json"
    auth_file.write_text("old.token")
    monkeypatch.setattr(f1_auth, "AUTH_DATA_FILE", auth_file)

    f1_auth.save_token("new.token")

    assert auth_file.read_text() == "new.token"
