"""
Unit tests for common/http_client.py.

Uses httpx.MockTransport (built into httpx, no extra test dependency) to
stub network calls, by patching the module's `httpx.AsyncClient` reference
with a factory that wires the mock transport in.
"""
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from common import http_client

_RealAsyncClient = httpx.AsyncClient  # captured before any monkeypatching, to avoid self-recursion


def _client_factory(transport: httpx.MockTransport) -> Callable[..., httpx.AsyncClient]:
    def factory(*, timeout: Any = None, **_ignored: Any) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=transport, timeout=timeout)
    return factory


@pytest.mark.asyncio
async def test_fetch_json_returns_parsed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["session_key"] == "9850"
        return httpx.Response(200, json={"ok": True, "count": 3})

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))

    result = await http_client.fetch_json("https://example.test/laps", params={"session_key": 9850})
    assert result == {"ok": True, "count": 3}


@pytest.mark.asyncio
async def test_fetch_json_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))

    with pytest.raises(httpx.HTTPStatusError):
        await http_client.fetch_json("https://example.test/laps")


@pytest.mark.asyncio
async def test_fetch_json_retries_once_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))

    result = await http_client.fetch_json("https://example.test/laps")
    assert result == {"ok": True}
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_fetch_json_gives_up_after_repeated_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset", request=request)

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))

    with pytest.raises(httpx.ConnectError):
        await http_client.fetch_json("https://example.test/laps")


@pytest.mark.asyncio
async def test_download_binary_writes_body_to_dest_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = b"\x00\x01fake-mp3-bytes\x02\x03"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    monkeypatch.setattr(http_client.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))

    dest = tmp_path / "nested" / "clip.mp3"
    result_path = await http_client.download_binary("https://example.test/clip.mp3", dest)

    assert result_path == dest
    assert dest.read_bytes() == body
