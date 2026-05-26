"""End-to-end tests for detection settings and status API endpoints."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

from magicwand.config import clear_config_cache


# ---------------------------------------------------------------------------
# GET /api/detection/status
# ---------------------------------------------------------------------------

async def test_detection_settings_get(client: httpx.AsyncClient) -> None:
    """GET /api/detection/status returns fps, trail_points, and config keys."""
    response = await client.get("/api/detection/status")

    assert response.status_code == 200
    body = response.json()

    assert "fps" in body, f"Missing 'fps' key in response: {body}"
    assert "trail_points" in body, f"Missing 'trail_points' key in response: {body}"
    assert "config" in body, f"Missing 'config' key in response: {body}"

    cfg = body["config"]
    assert "threshold" in cfg
    assert "min_area" in cfg
    assert "max_area" in cfg
    assert "blur_kernel" in cfg
    assert "trail_hold" in cfg
    assert "trail_fade" in cfg


# ---------------------------------------------------------------------------
# PUT /api/settings/detection
# ---------------------------------------------------------------------------

async def test_detection_settings_put(client: httpx.AsyncClient) -> None:
    """PUT /api/settings/detection with threshold=200 is reflected in the response."""
    response = await client.put(
        "/api/settings/detection",
        json={"threshold": 200},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["threshold"] == 200


async def test_detection_settings_put_invalid_key_ignored(
    client: httpx.AsyncClient,
) -> None:
    """PUT with an unknown key causes no error; valid fields remain unchanged."""
    # First capture the current threshold so we can verify it is unchanged.
    status_before = await client.get("/api/detection/status")
    threshold_before = status_before.json()["config"]["threshold"]

    response = await client.put(
        "/api/settings/detection",
        json={"nonexistent_key": 123},
    )

    assert response.status_code == 200
    body = response.json()

    # The known field must still be at its original value.
    assert body["threshold"] == threshold_before
