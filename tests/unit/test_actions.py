"""Unit tests for magicwand.actions — ActionConfig, ActionResult, ActionDispatcher."""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from magicwand.actions import ActionConfig, ActionResult, ActionDispatcher


# ---------------------------------------------------------------------------
# ActionConfig defaults
# ---------------------------------------------------------------------------

def test_action_config_defaults() -> None:
    """ActionConfig(url=...) fills in sensible defaults for all other fields."""
    config = ActionConfig(url="http://x")
    assert config.method == "GET"
    assert config.headers == {}
    assert config.body is None
    assert config.timeout == 5.0


# ---------------------------------------------------------------------------
# ActionDispatcher — successful dispatch
# ---------------------------------------------------------------------------

async def test_dispatch_success() -> None:
    """fire() returns ActionResult with success=True and status_code=200 on a 200 response."""
    dispatcher = ActionDispatcher()
    await dispatcher.start()

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.text = '{"ok": true}'

    with patch.object(dispatcher._client, "request", new_callable=AsyncMock, return_value=mock_response):
        result = await dispatcher.fire(ActionConfig(url="http://example.com"))

    assert result.success is True
    assert result.status_code == 200
    assert result.latency_ms >= 0
    assert result.error is None

    await dispatcher.stop()


# ---------------------------------------------------------------------------
# ActionDispatcher — timeout
# ---------------------------------------------------------------------------

async def test_dispatch_timeout() -> None:
    """fire() returns success=False with 'timeout' in the error on httpx.TimeoutException."""
    dispatcher = ActionDispatcher()
    await dispatcher.start()

    with patch.object(
        dispatcher._client,
        "request",
        new_callable=AsyncMock,
        side_effect=httpx.TimeoutException("timed out"),
    ):
        result = await dispatcher.fire(ActionConfig(url="http://example.com"))

    assert result.success is False
    assert result.error is not None
    assert "timeout" in result.error.lower()
    assert result.status_code is None

    await dispatcher.stop()


# ---------------------------------------------------------------------------
# ActionDispatcher — connection error
# ---------------------------------------------------------------------------

async def test_dispatch_connection_error() -> None:
    """fire() returns success=False with 'connection' in the error on httpx.ConnectError."""
    dispatcher = ActionDispatcher()
    await dispatcher.start()

    with patch.object(
        dispatcher._client,
        "request",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("connection refused"),
    ):
        result = await dispatcher.fire(ActionConfig(url="http://example.com"))

    assert result.success is False
    assert result.error is not None
    assert "connection" in result.error.lower()
    assert result.status_code is None

    await dispatcher.stop()


# ---------------------------------------------------------------------------
# ActionDispatcher — not started
# ---------------------------------------------------------------------------

async def test_dispatch_not_started() -> None:
    """fire() returns an error immediately when start() has not been called."""
    dispatcher = ActionDispatcher()
    result = await dispatcher.fire(ActionConfig(url="http://example.com"))

    assert result.success is False
    assert result.error is not None
    assert "not started" in result.error.lower()
    assert result.latency_ms == 0.0


# ---------------------------------------------------------------------------
# ActionDispatcher — last_result property
# ---------------------------------------------------------------------------

async def test_last_result_property() -> None:
    """last_result reflects the most recent ActionResult returned by fire()."""
    dispatcher = ActionDispatcher()
    await dispatcher.start()

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.text = "ok"

    with patch.object(dispatcher._client, "request", new_callable=AsyncMock, return_value=mock_response):
        result = await dispatcher.fire(ActionConfig(url="http://example.com"))

    assert dispatcher.last_result is result
    assert dispatcher.last_result.success is True

    await dispatcher.stop()
