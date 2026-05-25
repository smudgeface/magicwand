"""End-to-end tests for the gesture training UX (Phase 6)."""

from __future__ import annotations

import pytest


async def test_gestures_page_loads(client):
    resp = await client.get("/gestures")
    assert resp.status_code == 200
    assert "Gestures" in resp.text
    assert "gesture-list" in resp.text


async def test_train_page_loads(client):
    resp = await client.get("/train")
    assert resp.status_code == 200
    assert "/api/stream" in resp.text
    assert "gesture-name" in resp.text


async def test_gesture_detail_page_loads(client):
    # Create a gesture first
    await client.post("/api/gestures", json={"name": "test-detail"})
    resp = await client.get("/gesture/test-detail")
    assert resp.status_code == 200
    assert "test-detail" in resp.text
    # Cleanup
    await client.delete("/api/gestures/test-detail")


async def test_index_has_nav_bar(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "nav-bar" in resp.text
    assert "/gestures" in resp.text


async def test_training_workflow_api(client):
    """Full API-driven workflow: create → record → stop → add sample"""
    # Create
    resp = await client.post("/api/gestures", json={"name": "train-test"})
    assert resp.status_code == 201

    # Start recording
    resp = await client.post("/api/recording/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "recording"

    # Stop recording (may have too few points since it's immediate, that's ok)
    resp = await client.post("/api/recording/stop")
    assert resp.status_code == 200

    # Manually add a sample (circular gesture that passes segmentation)
    import math
    n = 40
    sample = [
        {"x": 0.5 + 0.2 * math.cos(2 * math.pi * i / n),
         "y": 0.5 + 0.2 * math.sin(2 * math.pi * i / n),
         "t": i * 0.033}
        for i in range(n)
    ]
    resp = await client.post("/api/gestures/train-test/samples", json=sample)
    assert resp.status_code == 201
    assert resp.json()["sample_count"] == 1

    # Verify
    resp = await client.get("/api/gestures/train-test")
    assert resp.json()["sample_count"] == 1

    # Cleanup
    await client.delete("/api/gestures/train-test")


async def test_static_js_files_serve(client):
    """Verify JS files are accessible"""
    for js in ["gestures.js", "train.js", "gesture-detail.js"]:
        resp = await client.get(f"/static/js/{js}")
        assert resp.status_code == 200
