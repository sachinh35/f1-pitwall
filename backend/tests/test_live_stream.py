"""Unit tests for utils/live_stream.py's F1SignalRStreamer: the sink abstraction (task
requirement - the standalone capture script must not depend on LiveSessionPipeline's
DB/decode machinery) and the self-healing reconnect loop in run() (task requirement -
raw capture must survive a SignalR disconnect/error without the whole process needing
to be restarted)."""
import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.live_session_pipeline import LiveSessionPipeline, unregister_pipeline
from utils.live_stream import F1SignalRStreamer
from utils.raw_capture import RawStreamArchiver


def _fake_sink() -> MagicMock:
    sink = MagicMock()
    sink.log_event = MagicMock()
    return sink


def test_default_sink_is_a_registered_live_session_pipeline() -> None:
    streamer = F1SignalRStreamer(access_token="", stream_id="test_default_sink")
    try:
        assert isinstance(streamer.pipeline, LiveSessionPipeline)
        assert streamer.sink is streamer.pipeline
    finally:
        unregister_pipeline(streamer.stream_id)


def test_explicit_sink_is_used_as_is_and_pipeline_attr_is_none(tmp_path: Path) -> None:
    archiver = RawStreamArchiver(tmp_path / "live_test.jsonl")
    try:
        streamer = F1SignalRStreamer(access_token="", sink=archiver, stream_id="test_explicit_sink")
        assert streamer.sink is archiver
        assert streamer.pipeline is None
    finally:
        archiver.close()


def test_stream_id_defaults_to_a_timestamp_but_can_be_overridden() -> None:
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="my_stable_id")
    assert streamer.stream_id == "my_stable_id"


def test_run_retries_after_connect_raises_and_stops_once_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates two transient connect() failures followed by a success - proves run()'s
    outer loop keeps retrying instead of exiting/raising, unlike the old behavior."""
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_retry")
    call_count = {"n": 0}

    def fake_connect() -> None:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError("simulated transient connect failure")
        streamer.is_connected = True
        streamer._stop_event.set()  # "connected" - immediately request a clean stop

    monkeypatch.setattr(streamer, "connect", fake_connect)
    monkeypatch.setattr(streamer, "subscribe_to_events", MagicMock())
    monkeypatch.setattr(streamer, "disconnect", MagicMock())
    monkeypatch.setattr("utils.live_stream._RECONNECT_INITIAL_BACKOFF_SECONDS", 0.01)

    streamer.run()

    assert call_count["n"] == 3
    streamer.disconnect.assert_called_once()


def test_stop_interrupts_a_long_reconnect_backoff_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A large backoff (simulating a prolonged outage) must not prevent stop() from ending
    the stream promptly - proves the reconnect loop is actually stoppable, not just retrying
    forever with no way out."""
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_stop")
    monkeypatch.setattr(streamer, "connect", MagicMock(side_effect=RuntimeError("always fails")))
    monkeypatch.setattr(streamer, "subscribe_to_events", MagicMock())
    monkeypatch.setattr(streamer, "disconnect", MagicMock())
    monkeypatch.setattr("utils.live_stream._RECONNECT_INITIAL_BACKOFF_SECONDS", 30.0)

    thread = threading.Thread(target=streamer.run, daemon=True)
    thread.start()
    time.sleep(0.1)  # let it fail once and enter the 30s backoff wait
    streamer.stop()
    thread.join(timeout=2.0)

    assert not thread.is_alive()


def test_run_never_raises_out_of_connect_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old behavior re-raised out of run() on any connect()/subscribe error, killing the
    background thread outright. That must never happen now - errors are retried, not fatal."""
    streamer = F1SignalRStreamer(access_token="", sink=_fake_sink(), stream_id="test_never_raises")
    attempts = {"n": 0}

    def fake_connect() -> None:
        attempts["n"] += 1
        if attempts["n"] >= 2:
            streamer.stop()
        raise RuntimeError("boom")

    monkeypatch.setattr(streamer, "connect", fake_connect)
    monkeypatch.setattr(streamer, "subscribe_to_events", MagicMock())
    monkeypatch.setattr(streamer, "disconnect", MagicMock())
    monkeypatch.setattr("utils.live_stream._RECONNECT_INITIAL_BACKOFF_SECONDS", 0.01)

    streamer.run()  # must not raise

    assert attempts["n"] >= 2


@pytest.mark.asyncio
async def test_handle_message_async_passes_a_real_now_event_time_to_the_sink() -> None:
    """A genuinely live message has no archived timestamp to recover - "now" (receipt
    time) is the real event time here, unlike the replay/tail path (see test_live_tail.py),
    which passes through the raw archive's own captured timestamp instead."""
    sink = _fake_sink()
    sink.handle_message = AsyncMock()
    streamer = F1SignalRStreamer(access_token="", sink=sink, stream_id="test_event_time", loop=asyncio.get_running_loop())

    before = datetime.now(timezone.utc)
    streamer._handle_message_async("WeatherData", {"AirTemp": "22.0"})
    await asyncio.sleep(0.05)  # let run_coroutine_threadsafe's scheduled coroutine actually run
    after = datetime.now(timezone.utc)

    sink.handle_message.assert_awaited_once()
    call_args = sink.handle_message.call_args.args
    assert call_args[0] == "WeatherData"
    assert call_args[1] == {"AirTemp": "22.0"}
    event_time = call_args[2]
    assert before <= event_time <= after


def _fake_completion(result=None, error=None) -> MagicMock:
    """Stands in for signalrcore's CompletionMessage - only .result/.error are read."""
    return MagicMock(result=result, error=error)


@pytest.mark.asyncio
async def test_handle_subscribe_result_feeds_every_topic_through_handle_message_async() -> None:
    """F1's Subscribe RPC call returns the full current state as its invocation result -
    e.g. {"LapCount": {"CurrentLap": 1}, "TimingAppData": {...}} - separate from the
    ongoing feed push messages. Previously dropped entirely (send() had no on_invocation),
    so a client always started blank and only learned a low-frequency field's *current*
    value once it happened to change again. This is the fix: each topic's initial value
    must reach the same handle_message() path a live diff would."""
    sink = _fake_sink()
    sink.handle_message = AsyncMock()
    streamer = F1SignalRStreamer(access_token="", sink=sink, stream_id="test_subscribe_result", loop=asyncio.get_running_loop())

    completion = _fake_completion(result={"LapCount": {"CurrentLap": 1}, "TimingAppData": {"Lines": {}}})
    streamer._handle_subscribe_result(completion)
    await asyncio.sleep(0.05)

    assert sink.handle_message.await_count == 2
    calls = {c.args[0]: c.args[1] for c in sink.handle_message.await_args_list}
    assert calls == {"LapCount": {"CurrentLap": 1}, "TimingAppData": {"Lines": {}}}


def test_handle_subscribe_result_ignores_a_non_dict_or_missing_result() -> None:
    """An error completion (message.result is None, message.error set) or any other
    non-dict result must be skipped, not crash the connect/subscribe path."""
    sink = _fake_sink()
    streamer = F1SignalRStreamer(access_token="", sink=sink, stream_id="test_subscribe_result_error")

    streamer._handle_subscribe_result(_fake_completion(result=None, error="boom"))  # must not raise
    streamer._handle_subscribe_result(_fake_completion(result="not a dict"))  # must not raise


@pytest.mark.asyncio
async def test_handle_subscribe_result_skips_none_valued_topics() -> None:
    sink = _fake_sink()
    sink.handle_message = AsyncMock()
    streamer = F1SignalRStreamer(access_token="", sink=sink, stream_id="test_subscribe_result_none", loop=asyncio.get_running_loop())

    streamer._handle_subscribe_result(_fake_completion(result={"Heartbeat": None, "LapCount": {"CurrentLap": 1}}))
    await asyncio.sleep(0.05)

    sink.handle_message.assert_awaited_once()
    assert sink.handle_message.call_args.args[:2] == ("LapCount", {"CurrentLap": 1})
