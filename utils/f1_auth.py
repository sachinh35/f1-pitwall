"""
F1 TV Pro Authentication Utility

The browser-based flow below (start_browser_auth_flow/check_browser_auth_status,
_AuthCallbackHandler) is ported from FastF1's fastf1/internals/f1auth.py (MIT
licensed, https://github.com/theOehrly/Fast-F1) and adapted for a non-blocking
FastAPI endpoint rather than FastF1's blocking CLI-oriented version - see
ATTRIBUTION.md. It relies on the community-run f1login.fastf1.dev relay and the
"FastF1 Companion" browser extension: the user logs into their F1TV account on
F1's/the relay's own page, in their own browser - the password never reaches
this codebase at all, only the resulting bearer token, posted back to a local
callback server we start for exactly this purpose.
"""
import json
import logging
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import jwt
import platformdirs
import requests
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger(__name__)

# F1 TV Pro authentication endpoint (Legacy/Password)
F1_AUTH_URL = "https://api.formula1.com/v1/account/subscriber/authenticate/by-password"
JWKS_URL = "https://api.formula1.com/static/jwks.json"
# The community-run relay the FastF1 Companion browser extension posts a captured
# F1TV login session back through - see the module docstring/ATTRIBUTION.md.
F1LOGIN_RELAY_URL = "https://f1login.fastf1.dev"

# Token storage
USER_DATA_DIR = Path(platformdirs.user_data_dir("f1-dashboard", ensure_exists=True))
AUTH_DATA_FILE = USER_DATA_DIR / "f1auth.json"

# F1 API Key - must be set via environment variable F1_API_KEY (for password auth)
F1_API_KEY = os.getenv("F1_API_KEY", "")


def _get_jwk_from_jwks_uri(jwks_uri, kid):
    """Fetch the JWKS data and find the key with matching kid."""
    response = requests.get(jwks_uri)
    response.raise_for_status()
    jwks = response.json()

    for key in jwks['keys']:
        if key['kid'] == kid:
            return key
    raise ValueError("Public key not found in JWKS for given kid.")


def validate_subscription_token(token: str) -> bool:
    """
    Verify the JWT token against F1's public keys.
    """
    try:
        # Decode headers to get the kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')
        
        if not kid:
            return False
            
        jwk = _get_jwk_from_jwks_uri(JWKS_URL, kid)

        # Convert JWK to public key
        public_key = RSAAlgorithm.from_jwk(jwk)

        # Verify and decode the token
        jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            verify=True
        )
        return True
    except Exception as e:
        logger.warning(f"Token validation failed: {e}")
        return False


def get_saved_token() -> Optional[str]:
    """Retrieve the saved subscription token from file."""
    if AUTH_DATA_FILE.exists():
        try:
            with open(AUTH_DATA_FILE, 'r') as f:
                token = f.read().strip()
                if token:
                    return token
        except Exception as e:
            logger.error(f"Error reading auth file: {e}")
    return None


async def authenticate_f1tv(email: str = "", password: str = "") -> Dict[str, Any]:
    """
    Authenticate with F1 TV Pro.
    
    Prioritizes:
    1. Saved subscription token (verified)
    2. Email/Password (Legacy/Unreliable)
    """
    # 1. Try saved token
    token = get_saved_token()
    if token:
        if validate_subscription_token(token):
            logger.info("Using valid saved subscription token")
            return {
                "access_token": token,
                "success": True,
                "method": "token"
            }
        else:
            logger.warning("Saved token is invalid or expired")

    # 2. Try password auth (Legacy)
    if email and password:
        if not F1_API_KEY:
            raise Exception("F1_API_KEY required for password authentication")
            
        try:
            logger.info("Attempting password authentication for %s", email)
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Origin": "https://www.formula1.com",
                    "apikey": F1_API_KEY,
                }
                
                response = await client.post(
                    F1_AUTH_URL,
                    headers=headers,
                    json={"Login": email, "Password": password},
                )
                response.raise_for_status()
                data = response.json()
                
                # Extract token logic (simplified from previous version)
                access_token = ""
                if isinstance(data, dict):
                    if "data" in data and "subscriptionToken" in data["data"]:
                        access_token = data["data"]["subscriptionToken"]
                    elif "SubscriptionToken" in data:
                        access_token = data["SubscriptionToken"]
                
                if access_token:
                    return {
                        "access_token": access_token,
                        "success": True,
                        "method": "password"
                    }
                    
        except Exception as e:
            logger.error(f"Password authentication failed: {e}")
            
    raise Exception("Authentication failed. Please use 'python auth_helper.py' to generate a new token.")


# ---- Browser-based auth flow (FastF1 Companion / f1login.fastf1.dev) ----
#
# Unlike FastF1's own get_auth_token(), which blocks the calling thread until the
# browser callback lands, these are split for a web API: start_browser_auth_flow()
# starts the local callback server and returns immediately with the URL for the
# caller to open; check_browser_auth_status() is polled afterwards to learn when
# (or whether) the login actually completed.

def _parse_login_session_payload(raw_body: bytes) -> Optional[str]:
    """
    Extract the subscription token from a callback POST body, matching FastF1's
    format exactly: {"loginSession": "<url-encoded JSON>"}, where the decoded JSON
    is {"data": {"subscriptionToken": "..."}, ...}. Returns None (never raises) for
    any malformed payload - a bad callback must not crash the local server.
    """
    try:
        outer = json.loads(raw_body.decode("utf-8"))
        login_session = outer.get("loginSession")
        if not login_session:
            return None
        decoded = urllib.parse.unquote(login_session)
        inner = json.loads(decoded)
        token = inner.get("data", {}).get("subscriptionToken")
        return token or None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Failed to parse browser-auth callback payload: %s", exc)
        return None


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    """Receives the one-shot callback POST from f1login.fastf1.dev. The captured
    token is stashed on the server instance (self.server), not a module global, so
    each browser-auth flow (and each test) is isolated from any other."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - matches BaseHTTPRequestHandler's signature
        pass  # silence the default per-request stderr logging

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming convention
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/auth":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        token = _parse_login_session_payload(raw_body)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

        self.server.captured_token = token  # type: ignore[attr-defined]


_browser_auth_lock = threading.Lock()
_browser_auth_state: Optional[Dict[str, Any]] = None


def start_browser_auth_flow() -> str:
    """
    Start a local callback server and return the URL to open in a browser to
    authenticate via the FastF1 Companion extension / f1login.fastf1.dev relay -
    see the module docstring. Starting a new flow while one is already pending
    replaces it (only one login is ever in flight for this single-user tool).
    """
    global _browser_auth_state
    with _browser_auth_lock:
        httpd = HTTPServer(("127.0.0.1", 0), _AuthCallbackHandler)
        httpd.captured_token = None  # type: ignore[attr-defined]
        port = httpd.server_port
        auth_url = f"{F1LOGIN_RELAY_URL}?port={port}"

        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        _browser_auth_state = {"httpd": httpd, "thread": thread, "port": port, "auth_url": auth_url}
        logger.info("Started browser auth flow on port=%s", port)
        return auth_url


def check_browser_auth_status() -> Dict[str, Any]:
    """
    Poll the in-flight browser auth flow. Returns one of:
      {"status": "not_started"}
      {"status": "pending", "auth_url": "..."}                 - still waiting on the callback
      {"status": "authenticated"}                               - token received, verified, and saved
      {"status": "failed", "error": "..."}                      - callback landed but the token was invalid
    Shuts down and clears the local server once it reaches a terminal state
    (authenticated or failed), so it never lingers holding a port open.
    """
    global _browser_auth_state
    with _browser_auth_lock:
        if _browser_auth_state is None:
            return {"status": "not_started"}

        httpd = _browser_auth_state["httpd"]
        token = getattr(httpd, "captured_token", None)

        if token is None:
            return {"status": "pending", "auth_url": _browser_auth_state["auth_url"]}

        _shutdown_browser_auth_server()

        if not validate_subscription_token(token):
            logger.warning("Browser auth callback produced a token that failed verification")
            return {"status": "failed", "error": "Received token failed verification against F1's public keys"}

        AUTH_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTH_DATA_FILE, "w") as f:
            f.write(token)
        logger.info("Browser auth flow completed - subscription token saved")
        return {"status": "authenticated"}


def _shutdown_browser_auth_server() -> None:
    """Must be called with _browser_auth_lock already held."""
    global _browser_auth_state
    if _browser_auth_state is None:
        return
    httpd = _browser_auth_state["httpd"]
    # shutdown() blocks until serve_forever()'s loop actually exits - safe to call
    # here since serve_forever() runs on the separate background thread, not this one.
    httpd.shutdown()
    httpd.server_close()
    _browser_auth_state = None
