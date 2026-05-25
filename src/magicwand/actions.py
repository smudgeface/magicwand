"""Action dispatch — fire HTTP requests when gestures are recognized."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ActionConfig:
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    timeout: float = 5.0


@dataclass
class ActionResult:
    success: bool
    status_code: int | None  # None on connection error
    response_body: str | None
    latency_ms: float
    error: str | None  # None on success


class ActionDispatcher:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._last_result: ActionResult | None = None

    async def start(self) -> None:
        """Create the httpx AsyncClient. Call during app startup."""
        self._client = httpx.AsyncClient(follow_redirects=True)

    async def stop(self) -> None:
        """Close the httpx client. Call during app shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fire(self, config: ActionConfig) -> ActionResult:
        """Execute an HTTP action and return the result.

        Measures latency. On timeout or connection error, returns
        ActionResult with success=False and the error message.
        Does not raise exceptions.
        """
        if self._client is None:
            return ActionResult(
                success=False,
                status_code=None,
                response_body=None,
                latency_ms=0.0,
                error="dispatcher not started",
            )

        t0 = time.monotonic()
        try:
            response = await self._client.request(
                method=config.method,
                url=config.url,
                headers=config.headers,
                content=config.body,
                timeout=config.timeout,
            )
            latency = (time.monotonic() - t0) * 1000
            result = ActionResult(
                success=response.is_success,
                status_code=response.status_code,
                response_body=response.text[:500],  # truncate long responses
                latency_ms=latency,
                error=None if response.is_success else f"HTTP {response.status_code}",
            )
        except httpx.TimeoutException:
            latency = (time.monotonic() - t0) * 1000
            result = ActionResult(
                success=False,
                status_code=None,
                response_body=None,
                latency_ms=latency,
                error="timeout",
            )
        except httpx.ConnectError as e:
            latency = (time.monotonic() - t0) * 1000
            result = ActionResult(
                success=False,
                status_code=None,
                response_body=None,
                latency_ms=latency,
                error=f"connection error: {e}",
            )
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            result = ActionResult(
                success=False,
                status_code=None,
                response_body=None,
                latency_ms=latency,
                error=str(e),
            )

        self._last_result = result
        return result

    @property
    def last_result(self) -> ActionResult | None:
        return self._last_result
