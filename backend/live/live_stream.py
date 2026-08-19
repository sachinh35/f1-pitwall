"""
Utility module for handling F1 SignalR live streaming.

The SignalR connection/negotiation/auth machinery below is unchanged from
the original implementation - that part already worked. What changed is
everything downstream of "a message arrived": instead of ad-hoc, half-finished
parsing (the old `_process_timing_data`/`_handle_message_async`), every
message now flows through a `LiveSessionPipeline` (live/live_session_pipeline.py),
the same one live/replay.py drives for simulated sessions - so live and
replayed sessions behave identically.
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import httpx
from signalrcore.hub_connection_builder import HubConnectionBuilder

from api_pydantic_models.confirmed_roster import ConfirmedRosterEntry
from live.live_session_pipeline import LiveSessionPipeline, get_pipeline, register_pipeline, unregister_pipeline

logger = logging.getLogger(__name__)

# Reconnect backoff for run()'s outer supervisor loop - separate from (and outside)
# signalrcore's own with_automatic_reconnect, which only retries a handful of times
# before giving up. This loop never gives up: it keeps calling connect() again,
# forever, until stop() is called - see run()'s docstring for why this matters.
_RECONNECT_INITIAL_BACKOFF_SECONDS = 5.0
_RECONNECT_MAX_BACKOFF_SECONDS = 60.0
_RECONNECT_BACKOFF_MULTIPLIER = 2.0


class StreamSink(Protocol):
    """What F1SignalRStreamer needs from whatever consumes its messages - satisfied by both
    LiveSessionPipeline (decode/broadcast/persist, the backend-owned live path) and
    RawStreamArchiver (live/raw_capture.py - archive-only, no DB/decode dependency, used by
    the standalone capture script so it never depends on anything that could make it crash)."""

    def log_event(self, event_type: str, data: Any) -> None: ...

    async def handle_message(self, event_name: str, payload: Any, event_time: Optional[datetime] = None) -> None: ...

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
        sink: Optional[StreamSink] = None,
        stream_id: Optional[str] = None,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.cookies = cookies
        self.loop = loop
        self.connection: Optional[Any] = None
        self.stream_id: str = stream_id or str(int(datetime.now().timestamp()))
        self.is_connected = False
        self.connected_event = threading.Event()
        self._stop_event = threading.Event()

        self._setup_log_directory()
        self.log_file_path: Path = self._log_file_path()

        # sink is optional so the backend-owned live path (main.py's /start-live-stream)
        # keeps its existing behavior unchanged - a full LiveSessionPipeline (decode,
        # SSE broadcast, DB persistence). The standalone capture script passes a lean
        # RawStreamArchiver instead, so it never depends on Postgres/decode logic - see
        # live/raw_capture.py and StreamSink above.
        if sink is not None:
            self.sink: StreamSink = sink
            self.pipeline: Optional[LiveSessionPipeline] = sink if isinstance(sink, LiveSessionPipeline) else None
        else:
            pipeline = LiveSessionPipeline(
                stream_id=self.stream_id, archive_path=self.log_file_path, confirmed_roster=confirmed_roster
            )
            register_pipeline(pipeline)
            self.pipeline = pipeline
            self.sink = pipeline

    def _setup_log_directory(self) -> None:
        """Create the stream logs directory if it doesn't exist."""
        STREAM_LOGS_DIR.mkdir(exist_ok=True)

    def _log_file_path(self) -> Path:
        timestamp = int(datetime.now().timestamp())
        return STREAM_LOGS_DIR / f"f1_stream_{timestamp}.jsonl"

    def _handle_message_async(self, event_name: str, payload: Any) -> None:
        """Schedule the pipeline's write path for one incoming message onto the asyncio loop.

        SignalR's own callback runs on a different thread than the asyncio
        loop, so this bridges into it via run_coroutine_threadsafe. event_time is "now" -
        this message is genuinely live, not replayed, so receipt time is the real event time."""
        if not self.loop:
            return
        event_time = datetime.now(timezone.utc)
        asyncio.run_coroutine_threadsafe(self.sink.handle_message(event_name, payload, event_time), self.loop)

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
                self.sink.log_event("connection", {"status": "connected", "url": url})
                logger.info(f"Successfully connected to F1 SignalR hub at {url}")
                return

            except Exception as e:
                last_error = e
                error_msg = f"Failed to connect to {url}: {str(e)}"
                logger.warning(error_msg)
                self.sink.log_event(
                    "error",
                    {"error": error_msg, "type": "connection_error", "url": url, "exception_type": type(e).__name__},
                )
                continue

        self.is_connected = False
        final_error_msg = f"Failed to connect to F1 SignalR hub with all attempted URLs. Last error: {str(last_error)}"
        logger.error(final_error_msg, exc_info=True)
        self.sink.log_event(
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
            self.sink.log_event("connection", {"status": "connected", "message": message})
            self.connected_event.set()

        def on_close(*args: Any) -> None:
            message = args[0] if args else None
            self.is_connected = False
            self.sink.log_event("connection", {"status": "disconnected", "message": message})
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
                    self.connection.send(method, [F1_TOPICS], on_invocation=self._handle_subscribe_result)
                    logger.info(f"Subscribed to {method} with topics")
                    self.sink.log_event("subscription", {"method": method, "topics": F1_TOPICS})
                    break
                except Exception as e:
                    logger.debug(f"Subscription method {method} failed: {e}")
                    continue
        except Exception as e:  # pragma: no cover - the inner per-method except always continues rather than propagating, so this can't currently be reached; kept as a defensive outer guard
            error_msg = f"Failed to subscribe to events: {str(e)}"
            logger.error(error_msg)
            self.sink.log_event("error", {"error": error_msg, "type": "subscription_error"})
            logger.warning("Continuing without explicit subscription - events may still be received")

    def _handle_subscribe_result(self, completion_message: Any) -> None:
        """
        signalrcore invokes on_invocation with a single CompletionMessage (not a list -
        the library's own type hint says List[CompletionMessage], but base_hub_connection's
        __on_completion_message calls handler.complete_callback(message) with just the one
        message; confirmed live, the list form raised TypeError: 'CompletionMessage' object
        is not iterable on the very first real Subscribe response).

        F1's `Subscribe` RPC call returns the full current state (one value per subscribed
        topic, e.g. {"LapCount": {"CurrentLap": 1, ...}, "TimingAppData": {...}, ...}) as
        its *invocation result* - entirely separate from the ongoing "feed" push messages
        on_feed_message handles. Previously dropped completely: send() was called without
        on_invocation, so every connect/reconnect started SessionState genuinely empty,
        rebuilt only from whatever incremental diffs happened to arrive afterward.

        For a high-frequency topic (TimingData changes every few hundred ms) that
        self-heals almost instantly and goes unnoticed. For a low-frequency one it doesn't:
        confirmed against two separate real captures (this session's live race and an
        older Qatar race capture) that F1 never re-sends LapCount's *current* value as a
        fresh diff, only the *next* one - so a client that missed the initial snapshot
        shows nothing until a full lap has elapsed, and would display "2" as the very
        first value it ever sees instead of "1". The same gap silently drops each driver's
        starting tyre compound (TimingAppData.Stints) until their first pit stop.

        Feeding each topic's initial value through the exact same handle_message() path a
        live diff uses seeds the reducer correctly immediately, with no changes needed to
        SessionState's handlers - a full initial value merges into empty state exactly
        the way a real diff would (deep_merge/Lines-merge are idempotent either way).
        """
        result = getattr(completion_message, "result", None)
        if not isinstance(result, dict):
            if getattr(completion_message, "error", None):
                logger.warning(f"Subscribe invocation returned an error: {completion_message.error}")
            else:
                logger.warning(f"Subscribe invocation result was not a topic dict: {type(result)!r}")
            return
        logger.info(f"Received initial state snapshot for {len(result)} topics from Subscribe result: {sorted(result.keys())}")
        for topic, value in result.items():
            if value is None:
                continue
            self._handle_message_async(topic, value)

    def stop(self) -> None:
        """Signal run()'s reconnect loop to stop retrying and shut down for good - the only
        way to permanently end a stream (a transient disconnect alone does not stop it; see run())."""
        self._stop_event.set()

    def disconnect(self) -> None:
        """Permanently stop this stream: signal the reconnect loop to give up (stop()) and
        tear down the live connection/archive immediately, without waiting for the run()
        thread to notice on its own."""
        self._stop_event.set()
        try:
            if self.connection and self.is_connected:
                self.connection.stop()
                self.is_connected = False
                self.connected_event.clear()
                self.sink.log_event("connection", {"status": "disconnected", "reason": "manual"})
                logger.info("Disconnected from F1 SignalR hub")
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")
        finally:
            unregister_pipeline(self.stream_id)
            close = getattr(self.sink, "close", None)
            if callable(close):
                close()

    def run(self) -> None:
        """
        Connect, subscribe, and keep the connection alive - self-healing on any disconnect
        or error, forever, until stop()/disconnect() is called. Runs in a background thread.

        signalrcore's own with_automatic_reconnect (see connect()) only retries a handful of
        times before giving up; this outer loop is what makes capture actually resilient -
        it keeps calling connect() again indefinitely, with capped exponential backoff
        between attempts, so a prolonged F1 SignalR outage delays capture but never
        permanently stops it short of the process being killed.
        """
        backoff = _RECONNECT_INITIAL_BACKOFF_SECONDS
        try:
            while not self._stop_event.is_set():
                try:
                    self.connect()
                    self.subscribe_to_events()
                    backoff = _RECONNECT_INITIAL_BACKOFF_SECONDS

                    logger.info("Stream is running. Waiting for events...")
                    self.sink.log_event("stream", {"status": "running"})

                    while self.is_connected and not self._stop_event.is_set():
                        time.sleep(1)

                except Exception as e:
                    error_msg = f"Stream error: {str(e)}"
                    logger.error(error_msg)
                    self.sink.log_event("error", {"error": error_msg, "type": "stream_error"})

                if self._stop_event.is_set():
                    break

                logger.warning("Stream disconnected - reconnecting in %.0fs", backoff)
                self.sink.log_event("stream", {"status": "reconnecting", "backoff_seconds": backoff})
                self._stop_event.wait(backoff)
                backoff = min(backoff * _RECONNECT_BACKOFF_MULTIPLIER, _RECONNECT_MAX_BACKOFF_SECONDS)
        except KeyboardInterrupt:
            logger.info("Stream interrupted by user")
            self.sink.log_event("stream", {"status": "interrupted", "reason": "user"})
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
    sink: Optional[StreamSink] = None,
    stream_id: Optional[str] = None,
    daemon: bool = True,
) -> F1SignalRStreamer:
    """
    Start a new live F1 SignalR stream in a background thread.

    `sink`/`stream_id`/`daemon` exist for scripts/capture_stream.py, the standalone raw
    capture process (see live/raw_capture.py's RawStreamArchiver) - it passes a lean
    archiver sink, a stable stream_id (so restarts keep the same identity/filename), and
    daemon=False (a daemon thread dies the instant its process's main thread exits, which
    is fine for a request handler inside the FastAPI process but wrong for a script whose
    entire purpose is to keep running).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    streamer = F1SignalRStreamer(
        access_token, refresh_token, cookies, loop=loop, confirmed_roster=confirmed_roster,
        sink=sink, stream_id=stream_id,
    )
    _active_streams[streamer.stream_id] = streamer

    thread = threading.Thread(target=streamer.run, daemon=daemon)
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
