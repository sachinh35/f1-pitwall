"""
Shared async HTTP client helpers.

Centralizes outbound HTTP calls (OpenF1 API fetches, team-radio audio downloads)
behind one consistent timeout/retry/error-logging policy, instead of each caller
opening its own ad-hoc httpx.AsyncClient inline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS: float = 30.0
_TRANSIENT_RETRY_ATTEMPTS: int = 2


async def fetch_json(
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """
    GET a URL and return its parsed JSON body.

    Retries once on a transient network error (httpx.TransportError) before
    giving up. Raises httpx.HTTPStatusError on non-2xx responses (not retried,
    since that's a real error, not a transient one).
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, _TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.TransportError as exc:
            last_error = exc
            logger.warning(
                "Transient error fetching %s (attempt %d/%d): %s",
                url, attempt, _TRANSIENT_RETRY_ATTEMPTS, exc,
            )
            continue
        except Exception:
            logger.exception("Error fetching %s", url)
            raise

    logger.error("Failed to fetch %s after %d attempts: %s", url, _TRANSIENT_RETRY_ATTEMPTS, last_error)
    assert last_error is not None
    raise last_error


async def download_binary(
    url: str,
    dest_path: Path,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """
    Stream a URL's binary body to `dest_path`, creating parent directories as needed.

    Returns `dest_path` on success. Raises httpx.HTTPStatusError on non-2xx responses.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
    logger.info("Downloaded %s -> %s", url, dest_path)
    return dest_path
