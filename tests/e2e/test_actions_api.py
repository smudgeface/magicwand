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
# Homebridge presets
# ---------------------------------------------------------------------------

_CONFIG_WITH_PRESETS = """\
[server]
host = "127.0.0.1"
port = 8000

[camera]
width = 640
height = 480
fps = 30
source = "mock"

[camera.mock]
dot_speed = 2.0

[homebridge]
host = "homebridge.local"
port = 8581

[[homebridge.presets]]
name = "Switch On"
method = "PUT"
url_template = "http://{host}:{port}/api/accessories/{accessory_id}"

[[homebridge.presets]]
name = "Switch Off"
method = "PUT"
url_template = "http://{host}:{port}/api/accessories/{accessory_id}"
"""


@pytest.fixture
def tmp_config_with_presets(tmp_path: Path) -> Path:
    """Write a config.toml that includes Homebridge presets to a temp dir."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(_CONFIG_WITH_PRESETS)
    return config_file


@pytest.fixture
def app_with_presets(tmp_config_with_presets: Path):
    """FastAPI app configured with Homebridge presets."""
    clear_config_cache()
    from magicwand.main import create_app
    a = create_app(config_path=tmp_config_with_presets)
    yield a
    clear_config_cache()


@pytest_asyncio.fixture
async def client_with_presets(app_with_presets):
    """AsyncClient with lifespan for the presets-enabled app."""
    async with LifespanManager(app_with_presets):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with_presets),
            base_url="http://testserver",
        ) as c:
            yield c


async def test_homebridge_presets(client_with_presets: httpx.AsyncClient) -> None:
    """GET /api/homebridge/presets returns a list of presets with required keys."""
    response = await client_with_presets.get("/api/homebridge/presets")
    assert response.status_code == 200
    presets = response.json()

    assert isinstance(presets, list)
    assert len(presets) >= 1

    # Verify each preset has the required shape.
    for preset in presets:
        assert "name" in preset
        assert "method" in preset
        assert "url_template" in preset

    # Verify our known preset names are present.
    names = [p["name"] for p in presets]
    assert "Switch On" in names
    assert "Switch Off" in names

    # url_template should have host/port filled in but {accessory_id} still as a placeholder.
    switch_on = next(p for p in presets if p["name"] == "Switch On")
    assert "homebridge.local" in switch_on["url_template"]
    assert "8581" in switch_on["url_template"]
    assert "{accessory_id}" in switch_on["url_template"]


async def test_homebridge_presets_empty(client: httpx.AsyncClient) -> None:
    """GET /api/homebridge/presets returns an empty list when no presets are configured."""
    response = await client.get("/api/homebridge/presets")
    assert response.status_code == 200
    assert response.json() == []
