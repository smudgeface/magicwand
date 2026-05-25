"""End-to-end tests for gesture matching API endpoints."""

from __future__ import annotations

import pytest
import httpx


async def test_matching_status_endpoint(client: httpx.AsyncClient) -> None:
    """GET /api/matching/status returns valid JSON with required fields."""
    response = await client.get("/api/matching/status")
    assert response.status_code == 200
    body = response.json()
    assert "state" in body
    assert body["state"] in ("idle", "tracking", "cooldown")
    # last_match is None until a gesture completes
    assert "last_match" in body
    assert body["last_match"] is None


async def test_matching_settings_update(client: httpx.AsyncClient) -> None:
    """PUT /api/settings/matching updates threshold and returns new config."""
    payload = {"distance_threshold": 1.5, "min_confidence": 0.7}
    response = await client.put("/api/settings/matching", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["distance_threshold"] == pytest.approx(1.5)
    assert body["min_confidence"] == pytest.approx(0.7)
    # Other fields are returned unchanged (defaults)
    assert "gap_timeout" in body
    assert "cooldown_time" in body
    assert "min_gesture_points" in body
    assert "resample_count" in body


async def test_matching_settings_update_unknown_key_ignored(client: httpx.AsyncClient) -> None:
    """PUT /api/settings/matching with unknown keys does not raise an error."""
    payload = {"distance_threshold": 1.0, "nonexistent_key": 99}
    response = await client.put("/api/settings/matching", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["distance_threshold"] == pytest.approx(1.0)
    assert "nonexistent_key" not in body


async def test_matching_settings_update_partial(client: httpx.AsyncClient) -> None:
    """PUT /api/settings/matching with a single field only updates that field."""
    # First, set a known baseline
    await client.put("/api/settings/matching", json={"distance_threshold": 2.0, "min_confidence": 0.6})

    # Now update only distance_threshold
    response = await client.put("/api/settings/matching", json={"distance_threshold": 0.8})
    assert response.status_code == 200
    body = response.json()
    assert body["distance_threshold"] == pytest.approx(0.8)
    assert body["min_confidence"] == pytest.approx(0.6)
