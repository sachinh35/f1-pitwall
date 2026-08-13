"""
Covers the parts of utils/live_stream.py's F1SignalRStreamer not already exercised by
test_live_stream.py (which focuses on the sink abstraction and run()'s reconnect loop):
the negotiation/connection/handler-registration/subscription machinery, plus the
module-level start_stream()/stop_stream() helpers. All real network I/O (httpx,
signalrcore's HubConnectionBuilder) is mocked - no real SignalR connection is made.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from utils import live_stream
from utils.live_stream import F1SignalRStreamer, start_stream, stop_stream


def _fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.log_event = MagicMock()
    return sink


# ---- _build_headers / _get_awsalbcors_cookie / _test_negotiation ----

def test_build_headers_includes_expected_fields() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_headers")
    headers = streamer._build_headers()
    assert headers["User-Agent"] == "BestHTTP"
    assert headers["Origin"] == "https://www.formula1.com"


def test_get_awsalbcors_cookie_returns_formatted_cookie_when_present() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_cookie_ok")
    fake_response = MagicMock()
    fake_response.cookies = {"AWSALBCORS": "abc123"}
    with patch.object(live_stream.httpx, "options", return_value=fake_response):
        result = streamer._get_awsalbcors_cookie()
    assert result == "AWSALBCORS=abc123"


def test_get_awsalbcors_cookie_returns_none_when_cookie_missing() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_cookie_missing")
    fake_response = MagicMock()
    fake_response.cookies = {}
    with patch.object(live_stream.httpx, "options", return_value=fake_response):
        assert streamer._get_awsalbcors_cookie() is None


def test_get_awsalbcors_cookie_returns_none_on_request_failure() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_cookie_error")
    with patch.object(live_stream.httpx, "options", side_effect=RuntimeError("network down")):
        assert streamer._get_awsalbcors_cookie() is None


def test_test_negotiation_returns_parsed_json_on_200() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_negotiation_ok")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"ConnectionId": "abc"}
    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.return_value = fake_response
    with patch.object(live_stream.httpx, "Client", return_value=fake_client):
        result = streamer._test_negotiation()
    assert result == {"ConnectionId": "abc"}


def test_test_negotiation_returns_none_on_non_json_response() -> None:
    import json as json_module

    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_negotiation_bad_json")
    fake_response = MagicMock(status_code=200, text="<html>not json</html>")
    fake_response.json.side_effect = json_module.JSONDecodeError("msg", "doc", 0)
    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.return_value = fake_response
    with patch.object(live_stream.httpx, "Client", return_value=fake_client):
        assert streamer._test_negotiation() is None


def test_test_negotiation_returns_none_on_non_200() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_negotiation_500")
    fake_response = MagicMock(status_code=500)
    fake_client = MagicMock()
    fake_client.__enter__.return_value.get.return_value = fake_response
    with patch.object(live_stream.httpx, "Client", return_value=fake_client):
        assert streamer._test_negotiation() is None


def test_test_negotiation_returns_none_on_exception() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_negotiation_error")
    with patch.object(live_stream.httpx, "Client", side_effect=RuntimeError("boom")):
        assert streamer._test_negotiation() is None


# ---- connect() ----

def _fake_hub_builder(connection: MagicMock) -> MagicMock:
    builder = MagicMock()
    builder.with_url.return_value = builder
    builder.configure_logging.return_value = builder
    builder.with_automatic_reconnect.return_value = builder
    builder.build.return_value = connection
    return builder


def test_connect_succeeds_on_first_url() -> None:
    streamer = F1SignalRStreamer(access_token="tok", sink=_fake_sink(), stream_id="test_connect_ok")
    connection = MagicMock()
    with patch.object(streamer, "_test_negotiation", return_value={"ok": True}), \
         patch.object(streamer, "_get_awsalbcors_cookie", return_value="AWSALBCORS=x"), \
         patch.object(live_stream, "HubConnectionBuilder", return_value=_fake_hub_builder(connection)), \
         patch.object(streamer.connected_event, "wait", return_value=True):
        streamer.connect()

    assert streamer.is_connected is True
    connection.start.assert_called_once()
    streamer.sink.log_event.assert_any_call("connection", {"status": "connected", "url": live_stream.F1_SIGNALR_URLS[0]})


def test_connect_raises_after_all_urls_fail() -> None:
    streamer = F1SignalRStreamer(access_token="tok", sink=_fake_sink(), stream_id="test_connect_fail")
    connection = MagicMock()
    connection.start.side_effect = RuntimeError("connection refused")
    with patch.object(streamer, "_test_negotiation", return_value=None), \
         patch.object(streamer, "_get_awsalbcors_cookie", return_value=None), \
         patch.object(live_stream, "HubConnectionBuilder", return_value=_fake_hub_builder(connection)):
        with pytest.raises(Exception, match="Failed to connect to F1 SignalR hub"):
            streamer.connect()

    assert streamer.is_connected is False


def test_connect_times_out_waiting_for_open_event_and_tries_next_url() -> None:
    streamer = F1SignalRStreamer(access_token="tok", sink=_fake_sink(), stream_id="test_connect_timeout")
    connection = MagicMock()
    with patch.object(streamer, "_test_negotiation", return_value=None), \
         patch.object(streamer, "_get_awsalbcors_cookie", return_value=None), \
         patch.object(live_stream, "HubConnectionBuilder", return_value=_fake_hub_builder(connection)), \
         patch.object(streamer.connected_event, "wait", return_value=False):
        with pytest.raises(Exception, match="Failed to connect to F1 SignalR hub"):
            streamer.connect()

    # One connect attempt per URL, each timing out.
    assert connection.start.call_count == len(live_stream.F1_SIGNALR_URLS)


def test_connect_stops_existing_connection_before_reconnecting() -> None:
    streamer = F1SignalRStreamer(access_token="tok", sink=_fake_sink(), stream_id="test_connect_replace")
    old_connection = MagicMock()
    streamer.connection = old_connection
    new_connection = MagicMock()
    with patch.object(streamer, "_test_negotiation", return_value=None), \
         patch.object(streamer, "_get_awsalbcors_cookie", return_value=None), \
         patch.object(live_stream, "HubConnectionBuilder", return_value=_fake_hub_builder(new_connection)), \
         patch.object(streamer.connected_event, "wait", return_value=True):
        streamer.connect()

    old_connection.stop.assert_called_once()


# ---- _setup_handlers ----

def test_setup_handlers_returns_early_with_no_connection() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_no_conn")
    streamer.connection = None
    streamer._setup_handlers()  # must not raise


def test_setup_handlers_on_open_and_on_close_update_state() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_open_close")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_open = connection.on_open.call_args.args[0]
    on_close = connection.on_close.call_args.args[0]

    on_open("hello-message")
    assert streamer.is_connected is True
    assert streamer.connected_event.is_set()

    on_close("bye-message")
    assert streamer.is_connected is False
    assert not streamer.connected_event.is_set()


def test_setup_handlers_on_feed_message_dispatches_typed_payload() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_feed")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_feed = connection.on.call_args_list[0].args[1]
    with patch.object(streamer, "_handle_message_async") as mock_handle:
        on_feed(["WeatherData", {"AirTemp": "22"}])
    mock_handle.assert_called_once_with("WeatherData", {"AirTemp": "22"})


def test_setup_handlers_on_feed_message_falls_back_to_raw_payload() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_feed_raw")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_feed = connection.on.call_args_list[0].args[1]
    with patch.object(streamer, "_handle_message_async") as mock_handle:
        on_feed({"not": "a list"})
    mock_handle.assert_called_once_with("feed", {"not": "a list"})


def test_setup_handlers_on_feed_message_handles_empty_args() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_feed_empty")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_feed = connection.on.call_args_list[0].args[1]
    on_feed()  # must not raise, just logs a warning


def test_setup_handlers_on_feed_message_swallows_handler_exceptions() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_feed_exc")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_feed = connection.on.call_args_list[0].args[1]
    with patch.object(streamer, "_handle_message_async", side_effect=RuntimeError("boom")):
        on_feed(["WeatherData", {}])  # must not raise


def test_setup_handlers_registers_feed_handler_registration_failure_is_swallowed() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_reg_fail")
    connection = MagicMock()
    connection.on.side_effect = RuntimeError("cannot register")
    streamer.connection = connection
    streamer._setup_handlers()  # must not raise despite both .on() calls failing


def test_setup_handlers_on_any_message_dispatches_as_unknown() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_handlers_any")
    connection = MagicMock()
    streamer.connection = connection
    streamer._setup_handlers()

    on_any = connection.on.call_args_list[1].args[1]
    with patch.object(streamer, "_handle_message_async") as mock_handle:
        on_any("single-arg")
    mock_handle.assert_called_once_with("unknown", "single-arg")


# ---- subscribe_to_events ----

def test_subscribe_to_events_raises_when_not_connected() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_sub_not_connected")
    with pytest.raises(RuntimeError, match="Not connected"):
        streamer.subscribe_to_events()


def test_subscribe_to_events_succeeds_on_first_method() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_sub_ok")
    streamer.connection = MagicMock()
    streamer.is_connected = True

    streamer.subscribe_to_events()

    streamer.connection.send.assert_called_once()
    assert streamer.connection.send.call_args.args[0] == "Subscribe"
    streamer.sink.log_event.assert_any_call("subscription", {"method": "Subscribe", "topics": live_stream.F1_TOPICS})


def test_subscribe_to_events_falls_back_through_methods_on_failure() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_sub_fallback")
    streamer.connection = MagicMock()
    streamer.connection.send.side_effect = [RuntimeError("nope"), RuntimeError("nope"), None]
    streamer.is_connected = True

    streamer.subscribe_to_events()

    assert streamer.connection.send.call_count == 3


def test_subscribe_to_events_does_not_raise_when_every_method_fails() -> None:
    """Every send() failure is caught (and logged at debug level) inside the per-method
    try/except, which always `continue`s rather than propagating - so the surrounding
    try/except (the one that would log an "error" sink event) can never actually fire
    through this path; see the `# pragma: no cover` on that branch in live_stream.py."""
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_sub_all_fail")
    streamer.connection = MagicMock()
    streamer.connection.send.side_effect = RuntimeError("nope")
    streamer.is_connected = True

    streamer.subscribe_to_events()  # must not raise

    assert streamer.connection.send.call_count == 3
    error_calls = [c for c in streamer.sink.log_event.call_args_list if c.args[0] == "error"]
    assert error_calls == []


# ---- disconnect() ----

def test_disconnect_stops_connection_and_closes_sink() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_disconnect_ok")
    streamer.connection = MagicMock()
    streamer.is_connected = True
    streamer.sink.close = MagicMock()

    streamer.disconnect()

    streamer.connection.stop.assert_called_once()
    assert streamer.is_connected is False
    assert streamer._stop_event.is_set()
    streamer.sink.close.assert_called_once()


def test_disconnect_is_a_noop_when_not_connected() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_disconnect_not_connected")
    streamer.connection = None
    streamer.is_connected = False

    streamer.disconnect()  # must not raise


def test_disconnect_swallows_stop_exceptions() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_disconnect_exc")
    streamer.connection = MagicMock()
    streamer.connection.stop.side_effect = RuntimeError("boom")
    streamer.is_connected = True

    streamer.disconnect()  # must not raise


def test_disconnect_handles_sink_with_no_close_method() -> None:
    sink = _fake_sink()
    del sink.close  # MagicMock auto-creates attrs, so explicitly remove it
    streamer = F1SignalRStreamer(access_token="", sink=sink, stream_id="test_disconnect_no_close")
    streamer.connection = None
    streamer.is_connected = False

    streamer.disconnect()  # must not raise despite sink having no .close


# ---- _handle_message_async with no loop ----

def test_handle_message_async_returns_early_with_no_loop() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_no_loop", loop=None)
    streamer._handle_message_async("WeatherData", {})  # must not raise
    streamer.sink.handle_message.assert_not_called()


# ---- get_stream_info ----

def test_get_stream_info() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_info")
    info = streamer.get_stream_info()
    assert info["stream_id"] == "test_info"
    assert info["is_connected"] is False


# ---- run()'s inner "connected and waiting for events" loop ----

def test_run_inner_loop_sleeps_while_connected_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_inner_loop")

    def fake_connect() -> None:
        streamer.is_connected = True

    sleep_calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        sleep_calls["n"] += 1
        streamer._stop_event.set()  # end the inner loop after exactly one real sleep call

    monkeypatch.setattr(streamer, "connect", fake_connect)
    monkeypatch.setattr(streamer, "subscribe_to_events", MagicMock())
    monkeypatch.setattr(streamer, "disconnect", MagicMock())
    monkeypatch.setattr(live_stream.time, "sleep", fake_sleep)

    streamer.run()

    assert sleep_calls["n"] == 1


def test_run_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_kb_interrupt")
    monkeypatch.setattr(streamer, "connect", MagicMock(side_effect=KeyboardInterrupt()))
    monkeypatch.setattr(streamer, "disconnect", MagicMock())

    streamer.run()  # must not raise

    interrupted_calls = [
        c for c in streamer.sink.log_event.call_args_list
        if c.args[0] == "stream" and c.args[1].get("status") == "interrupted"
    ]
    assert len(interrupted_calls) == 1
    streamer.disconnect.assert_called_once()


# ---- start_stream() / stop_stream() ----

def test_start_stream_registers_and_starts_a_background_thread() -> None:
    fake_streamer = MagicMock()
    fake_streamer.stream_id = "started-stream"
    fake_thread = MagicMock()

    with patch.object(live_stream, "F1SignalRStreamer", return_value=fake_streamer), \
         patch.object(live_stream.threading, "Thread", return_value=fake_thread) as mock_thread_cls:
        result = start_stream(access_token="tok", stream_id="started-stream")

    assert result is fake_streamer
    assert live_stream._active_streams["started-stream"] is fake_streamer
    mock_thread_cls.assert_called_once_with(target=fake_streamer.run, daemon=True)
    fake_thread.start.assert_called_once()
    del live_stream._active_streams["started-stream"]


def test_start_stream_uses_none_loop_when_no_running_event_loop() -> None:
    fake_streamer = MagicMock()
    fake_streamer.stream_id = "no-loop-stream"

    with patch.object(live_stream, "F1SignalRStreamer", return_value=fake_streamer) as mock_cls, \
         patch.object(live_stream.threading, "Thread", return_value=MagicMock()):
        start_stream(access_token="tok", stream_id="no-loop-stream")

    assert mock_cls.call_args.kwargs["loop"] is None
    del live_stream._active_streams["no-loop-stream"]


def test_stop_stream_disconnects_and_removes_active_stream() -> None:
    fake_streamer = MagicMock()
    live_stream._active_streams["to-stop"] = fake_streamer

    result = stop_stream("to-stop")

    assert result is True
    fake_streamer.disconnect.assert_called_once()
    assert "to-stop" not in live_stream._active_streams


def test_stop_stream_returns_false_when_not_found() -> None:
    assert stop_stream("does-not-exist") is False
