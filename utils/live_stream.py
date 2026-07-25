"""
Utility module for handling F1 SignalR live streaming.

The SignalR connection/negotiation/auth machinery below is unchanged from
the original implementation - that part already worked. What changed is
everything downstream of "a message arrived": instead of ad-hoc, half-finished
parsing (the old `_process_timing_data`/`_handle_message_async`), every
message now flows through a `LiveSessionPipeline` (utils/live_session_pipeline.py),
the same one utils/replay.py drives for simulated sessions - so live and
replayed sessions behave identically.
"""
import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from signalrcore.hub_connection_builder import HubConnectionBuilder

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from utils.live_session_pipeline import LiveSessionPipeline, get_pipeline, register_pipeline, unregister_pipeline

logger = logging.getLogger(__name__)

# F1 SignalR Hub Configuration
# The negotiation endpoint is: https://livetiming.formula1.com/signalrcore/negotiate
# The hub name for F1 live timing is typically "Streaming"
F1_SIGNALR_BASE_URL = "https://livetiming.formula1.com/signalrcore"
F1_SIGNALR_NEGOTIATE_URL = f"{F1_SIGNALR_BASE_URL}/negotiate"
F1_SIGNALR_HUB_NAME = "Streaming"  # F1's SignalR hub name

# Try different possible endpoints (will try them in order if connection fails):
F1_SIGNALR_URLS = [
    "wss://livetiming.formula1.com/signalrcore",  # Direct WebSocket (preferred by Fast-F1)
    F1_SIGNALR_BASE_URL,  # HTTPS base URL
    "https://livetiming.formula1.com/signalr",  # Fallback (older format)
]
F1_SIGNALR_URL = F1_SIGNALR_URLS[0]  # Default to first URL

# Directory to store stream log files
STREAM_LOGS_DIR = Path("stream_logs")

# Topics to subscribe to (from Fast-F1)
F1_TOPICS = [
    "Heartbeat", "AudioStreams", "DriverList",
    "ExtrapolatedClock", "RaceControlMessages",
    "SessionInfo", "SessionStatus", "TeamRadio",
    "TimingAppData", "TimingStats", "TrackStatus",
    "WeatherData", "Position.z", "CarData.z",
    "ContentStreams", "SessionData", "TimingData",
    "TopThree", "RcmSeries", "LapCount"
]


class F1SignalRStreamer:
    """Handles F1 SignalR connection and streams messages into a LiveSessionPipeline."""

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        cookies: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        confirmed_roster: Optional[List[ConfirmedRosterEntry]] = None,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.cookies = cookies
        self.loop = loop
        self.connection: Optional[Any] = None
        self.stream_id: str = str(int(datetime.now().timestamp()))
        self.is_connected = False
        self.connected_event = threading.Event()

        self._setup_log_directory()
        self.log_file_path: Path = self._log_file_path()

        self.pipeline = LiveSessionPipeline(
            stream_id=self.stream_id, archive_path=self.log_file_path, confirmed_roster=confirmed_roster
        )
        register_pipeline(self.pipeline)

    def _setup_log_directory(self) -> None:
        """Create the stream logs directory if it doesn't exist."""
        STREAM_LOGS_DIR.mkdir(exist_ok=True)

    def _log_file_path(self) -> Path:
        timestamp = int(datetime.now().timestamp())
        return STREAM_LOGS_DIR / f"f1_stream_{timestamp}.jsonl"

    def _handle_message_async(self, event_name: str, payload: Any) -> None:
        """Schedule the pipeline's write path for one incoming message onto the asyncio loop.

        SignalR's own callback runs on a different thread than the asyncio
        loop, so this bridges into it via run_coroutine_threadsafe."""
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self.pipeline.process_message(event_name, payload), self.loop)

    def _build_headers(self) -> Dict[str, str]:
        """Build authentication headers for SignalR connection."""
        headers = {
            "User-Agent": "BestHTTP",
            "Origin": "https://www.formula1.com",
            "Referer": "https://www.formula1.com/",
            "Accept-Encoding": "gzip, identity",
        }
        return headers

    def _get_awsalbcors_cookie(self) -> Optional[str]:
        """Fetch AWSALBCORS cookie via OPTIONS request to negotiate endpoint. Required for F1 SignalR connection."""
        try:
            response = httpx.options(F1_SIGNALR_NEGOTIATE_URL, headers={"User-Agent": "BestHTTP"})
            cookie = response.cookies.get("AWSALBCORS")
            if cookie:
                return f"AWSALBCORS={cookie}"
            logger.warning("AWSALBCORS cookie not found in response")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch AWSALBCORS cookie: {e}")
            return None

    def _test_negotiation(self) -> Optional[Dict[str, Any]]:
        """Manually test the SignalR negotiation endpoint (GET with query params, SignalR Core style)."""
        try:
            import urllib.parse

            headers = self._build_headers()
            connection_data = json.dumps([{"name": F1_SIGNALR_HUB_NAME}])
            encoded_connection_data = urllib.parse.quote(connection_data)
            negotiate_url = f"{F1_SIGNALR_NEGOTIATE_URL}?connectionData={encoded_connection_data}&clientProtocol=1.5"

            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(negotiate_url, headers=headers)
                if response.status_code == 200:
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        logger.warning(f"Negotiation returned non-JSON response: {response.text[:200]}")
                        return None
                logger.warning(f"Negotiation failed with status {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Error testing negotiation: {e}", exc_info=True)
            return None

    def connect(self) -> None:
        """Establish connection to F1 SignalR hub. Tries multiple URL formats if needed."""
        last_error = None

        if self._test_negotiation():
            logger.info("Negotiation test successful - proceeding with connection")
        else:
            logger.warning("Negotiation test failed or skipped - will attempt connection anyway")

        for url in F1_SIGNALR_URLS:
            try:
                logger.info(f"Attempting to connect to F1 SignalR hub: {url}")

                aws_cookie = self._get_awsalbcors_cookie()
                headers = self._build_headers()
                if aws_cookie:
                    headers["Cookie"] = f'{headers.get("Cookie", "")}; {aws_cookie}'.lstrip("; ")

                connection_options: Dict[str, Any] = {"headers": headers}
                if self.access_token:
                    connection_options["access_token_factory"] = lambda: self.access_token

                if self.connection:
                    try:
                        self.connection.stop()
                    except Exception:
                        pass

                self.connection = (
                    HubConnectionBuilder()
                    .with_url(url, options=connection_options)
                    .configure_logging(logging.INFO)
                    .with_automatic_reconnect(
                        {"type": "raw", "keep_alive_interval": 10, "reconnect_interval": 5, "max_attempts": 5}
                    )
                    .build()
                )

                self._setup_handlers()

                logger.info(f"Attempting to start SignalR connection to {url}...")
                self.connection.start()

                if not self.connected_event.wait(timeout=10):
                    logger.error("Timeout waiting for connection to open")
                    self.connection.stop()
                    raise TimeoutError("Failed to connect to SignalR hub")

                self.is_connected = True
                self.pipeline.log_event("connection", {"status": "connected", "url": url})
                logger.info(f"Successfully connected to F1 SignalR hub at {url}")
                return

            except Exception as e:
                last_error = e
                error_msg = f"Failed to connect to {url}: {str(e)}"
                logger.warning(error_msg)
                self.pipeline.log_event(
                    "error",
                    {"error": error_msg, "type": "connection_error", "url": url, "exception_type": type(e).__name__},
                )
                continue

        self.is_connected = False
        final_error_msg = f"Failed to connect to F1 SignalR hub with all attempted URLs. Last error: {str(last_error)}"
        logger.error(final_error_msg, exc_info=True)
        self.pipeline.log_event(
            "error",
            {
                "error": final_error_msg,
                "type": "connection_error",
                "exception_type": type(last_error).__name__ if last_error else "Unknown",
                "attempted_urls": F1_SIGNALR_URLS,
            },
        )
        raise Exception(final_error_msg) from last_error

    def _setup_handlers(self) -> None:
        """Set up SignalR event handlers."""
        if not self.connection:
            return

        def on_open(*args: Any) -> None:
            message = args[0] if args else None
            self.is_connected = True
            self.pipeline.log_event("connection", {"status": "connected", "message": message})
            self.connected_event.set()

        def on_close(*args: Any) -> None:
            message = args[0] if args else None
            self.is_connected = False
            self.pipeline.log_event("connection", {"status": "disconnected", "message": message})
            self.connected_event.clear()

        self.connection.on_open(on_open)
        self.connection.on_close(on_close)

        def on_feed_message(*args: Any) -> None:
            try:
                if args and len(args) > 0:
                    payload = args[0]
                    if isinstance(payload, list) and len(payload) >= 2:
                        message_type, message_data = payload[0], payload[1]
                        self._handle_message_async(message_type, message_data)
                    else:
                        self._handle_message_async("feed", payload)
                else:
                    logger.warning("Received empty feed message")
            except Exception as e:
                logger.error(f"Error processing feed message: {e}")

        try:
            self.connection.on("feed", on_feed_message)
            logger.info("Registered 'feed' event handler")
        except Exception as e:
            logger.error(f"Could not register 'feed' handler: {e}")

        def on_any_message(*args: Any) -> None:
            data = args[0] if len(args) == 1 else args
            self._handle_message_async("unknown", data)

        try:
            self.connection.on("message", on_any_message)
        except Exception:
            pass

    def subscribe_to_events(self) -> None:
        """Subscribe to F1 live timing events."""
        if not self.connection or not self.is_connected:
            raise RuntimeError("Not connected to SignalR hub")

        try:
            for method in ("Subscribe", "SubscribeToTiming", "SubscribeToLiveTiming"):
                try:
                    self.connection.send(method, [F1_TOPICS])
                    logger.info(f"Subscribed to {method} with topics")
                    self.pipeline.log_event("subscription", {"method": method, "topics": F1_TOPICS})
                    break
                except Exception as e:
                    logger.debug(f"Subscription method {method} failed: {e}")
                    continue
        except Exception as e:
            error_msg = f"Failed to subscribe to events: {str(e)}"
            logger.error(error_msg)
            self.pipeline.log_event("error", {"error": error_msg, "type": "subscription_error"})
            logger.warning("Continuing without explicit subscription - events may still be received")

    def disconnect(self) -> None:
        """Disconnect from SignalR hub and close the pipeline's archive file."""
        try:
            if self.connection and self.is_connected:
                self.connection.stop()
                self.is_connected = False
                self.connected_event.clear()
                self.pipeline.log_event("connection", {"status": "disconnected", "reason": "manual"})
                logger.info("Disconnected from F1 SignalR hub")
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")
        finally:
            unregister_pipeline(self.stream_id)

    def run(self) -> None:
        """Connect, subscribe, and keep alive. Runs in a background thread."""
        try:
            self.connect()
            self.subscribe_to_events()

            logger.info("Stream is running. Waiting for events...")
            self.pipeline.log_event("stream", {"status": "running"})

            import time
            while self.is_connected:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Stream interrupted by user")
            self.pipeline.log_event("stream", {"status": "interrupted", "reason": "user"})
        except Exception as e:
            error_msg = f"Stream error: {str(e)}"
            logger.error(error_msg)
            self.pipeline.log_event("error", {"error": error_msg, "type": "stream_error"})
            raise
        finally:
            self.disconnect()

    def get_stream_info(self) -> Dict[str, Any]:
        """Get information about the current stream."""
        return {
            "stream_id": self.stream_id,
            "log_file": str(self.log_file_path),
            "is_connected": self.is_connected,
        }


# Global dictionary to track active live (non-replay) streams, by stream_id.
_active_streams: Dict[str, F1SignalRStreamer] = {}


def start_stream(
    access_token: str,
    refresh_token: Optional[str] = None,
    cookies: Optional[str] = None,
    confirmed_roster: Optional[List[ConfirmedRosterEntry]] = None,
) -> F1SignalRStreamer:
    """Start a new live F1 SignalR stream in a background thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    streamer = F1SignalRStreamer(access_token, refresh_token, cookies, loop=loop, confirmed_roster=confirmed_roster)
    _active_streams[streamer.stream_id] = streamer

    thread = threading.Thread(target=streamer.run, daemon=True)
    thread.start()

    return streamer


def stop_stream(stream_id: str) -> bool:
    """Stop an active live stream. Returns True if it was found and stopped."""
    streamer = _active_streams.get(stream_id)
    if streamer:
        streamer.disconnect()
        del _active_streams[stream_id]
        return True
    return False
