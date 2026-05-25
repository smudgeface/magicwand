"""End-to-end tests for gesture and recording API endpoints."""

from __future__ import annotations

import pytest
import httpx


# ---------------------------------------------------------------------------
# Gesture CRUD
# ---------------------------------------------------------------------------

async def test_create_and_list_gesture(client: httpx.AsyncClient) -> None:
    """POST /api/gestures creates a gesture that appears in GET /api/gestures."""
    response = await client.post("/api/gestures", json={"name": "test-spell"})
    assert response.status_code == 201
    assert response.json()["name"] == "test-spell"

    list_response = await client.get("/api/gestures")
    assert list_response.status_code == 200
    names = [g["name"] for g in list_response.json()]
    assert "test-spell" in names


async def test_create_invalid_name(client: httpx.AsyncClient) -> None:
    """POST /api/gestures with an invalid name returns 400."""
    response = await client.post("/api/gestures", json={"name": "Invalid!"})
    assert response.status_code == 400


async def test_delete_gesture(client: httpx.AsyncClient) -> None:
    """DELETE /api/gestures/{name} removes the gesture; GET list is then empty."""
    await client.post("/api/gestures", json={"name": "vanish-spell"})

    delete_response = await client.delete("/api/gestures/vanish-spell")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] == "vanish-spell"

    list_response = await client.get("/api/gestures")
    names = [g["name"] for g in list_response.json()]
    assert "vanish-spell" not in names


async def test_add_sample_via_api(client: httpx.AsyncClient) -> None:
    """POST /api/gestures/{name}/samples stores a sample; GET detail shows sample_count=1."""
    await client.post("/api/gestures", json={"name": "incendio"})

    points = [{"x": i * 0.1, "y": i * 0.1, "t": float(i)} for i in range(5)]
    sample_response = await client.post("/api/gestures/incendio/samples", json=points)
    assert sample_response.status_code == 201
    assert sample_response.json()["sample_count"] == 1

    detail_response = await client.get("/api/gestures/incendio")
    assert detail_response.status_code == 200
    assert detail_response.json()["sample_count"] == 1


# ---------------------------------------------------------------------------
# Recording endpoints
# ---------------------------------------------------------------------------

async def test_recording_status_default(client: httpx.AsyncClient) -> None:
    """GET /api/recording/status returns state='idle' and point_count=0 initially."""
    response = await client.get("/api/recording/status")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "idle"
    assert body["point_count"] == 0


async def test_start_and_stop_recording(client: httpx.AsyncClient) -> None:
    """POST start transitions to 'recording'; POST stop returns a valid response shape."""
    start_response = await client.post("/api/recording/start")
    assert start_response.status_code == 200
    assert start_response.json()["state"] == "recording"

    stop_response = await client.post("/api/recording/stop")
    assert stop_response.status_code == 200
    body = stop_response.json()
    # The response always contains "state" and "sample" (or reason).
    assert "state" in body
    # sample may be None (too few points captured in the short test window)
    # or a list of point dicts — both are valid outcomes.
    assert "sample" in body or "point_count" in body
