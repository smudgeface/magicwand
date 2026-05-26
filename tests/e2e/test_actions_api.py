"""End-to-end tests for action dispatch and Homebridge API endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from pathlib import Path

from asgi_lifespan import LifespanManager
from magicwand.config import clear_config_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_gesture(client: httpx.AsyncClient, name: str) -> None:
    """Create a gesture via the API; assert 201."""
    response = await client.post("/api/gestures", json={"name": name})
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Action CRUD
# ---------------------------------------------------------------------------

async def test_set_action_on_gesture(client: httpx.AsyncClient) -> None:
    """PUT /api/gestures/{name}/action stores an action; GET detail reflects it."""
    await _create_gesture(client, "lumos")

    action = {"url": "http://homebridge.local:8581/api/on", "method": "PUT"}
    put_response = await client.put("/api/gestures/lumos/action", json=action)
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["name"] == "lumos"
    assert body["action"]["url"] == action["url"]
    assert body["action"]["method"] == action["method"]

    detail = await client.get("/api/gestures/lumos")
    assert detail.status_code == 200
    assert detail.json()["action"] is not None
    assert detail.json()["action"]["url"] == action["url"]


async def test_clear_action(client: httpx.AsyncClient) -> None:
    """DELETE /api/gestures/{name}/action clears the action; GET detail shows action=null."""
    await _create_gesture(client, "nox")

    action = {"url": "http://homebridge.local:8581/api/off", "method": "PUT"}
    await client.put("/api/gestures/nox/action", json=action)

    delete_response = await client.delete("/api/gestures/nox/action")
    assert delete_response.status_code == 200
    assert delete_response.json()["action"] is None

    detail = await client.get("/api/gestures/nox")
    assert detail.status_code == 200
    assert detail.json()["action"] is None


async def test_set_action_invalid_gesture(client: httpx.AsyncClient) -> None:
    """PUT /api/gestures/{name}/action on a nonexistent gesture returns 404."""
    response = await client.put(
        "/api/gestures/nonexistent/action",
        json={"url": "http://example.com"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test-fire endpoint
# ---------------------------------------------------------------------------

async def test_test_action_fires_request(client: httpx.AsyncClient) -> None:
    """POST action/test against a refused port returns a well-formed failure response."""
    await _create_gesture(client, "expelliarmus")

    # Port 1 refuses connections immediately — we test the dispatch path,
    # not a live server.
    action = {"url": "http://127.0.0.1:1/test", "method": "GET"}
    await client.put("/api/gestures/expelliarmus/action", json=action)

    test_response = await client.post(
        "/api/gestures/expelliarmus/action/test",
        timeout=10.0,  # allow time for the connection attempt + refusal
    )
    assert test_response.status_code == 200
    body = test_response.json()
    assert body["success"] is False
    assert body["error"] is not None
    assert isinstance(body["latency_ms"], (int, float))
    # status_code is None on connection failure — serialised as null in JSON
    assert body["status_code"] is None


async def test_test_action_no_gesture(client: httpx.AsyncClient) -> None:
    """POST action/test on a nonexistent gesture returns 404."""
    response = await client.post("/api/gestures/ghost-gesture/action/test")
    assert response.status_code == 404


async def test_test_action_no_action_configured(client: httpx.AsyncClient) -> None:
    """POST action/test when no action is set returns 400."""
    await _create_gesture(client, "accio")
    # No action configured — fire test immediately.
    response = await client.post("/api/gestures/accio/action/test")
    assert response.status_code == 400
    assert "action" in response.json()["error"].lower()


# ---------------------------------------------------------------------------
# Homebridge status
# ---------------------------------------------------------------------------


async def test_homebridge_status(client: httpx.AsyncClient) -> None:
    """GET /api/homebridge/status returns connection info."""
    response = await client.get("/api/homebridge/status")
    assert response.status_code == 200
    data = response.json()
    assert "configured" in data
    assert "connected" in data
