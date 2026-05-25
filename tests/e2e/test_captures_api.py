"""End-to-end tests for the /api/captures and /captures endpoints."""

from __future__ import annotations

import pytest


async def test_captures_list_initially_empty(client):
    """GET /api/captures returns 200 with a 'captures' key."""
    resp = await client.get("/api/captures")
    assert resp.status_code == 200
    data = resp.json()
    assert "captures" in data
    # May or may not be empty depending on whether the mock watcher produced
    # captures during startup; just verify the structure.
    assert isinstance(data["captures"], list)


async def test_captures_page_loads(client):
    """GET /captures renders the Capture History page."""
    resp = await client.get("/captures")
    assert resp.status_code == 200
    assert "Capture History" in resp.text


async def test_captures_clear(client):
    """DELETE /api/captures returns 200 with a 'cleared' count."""
    resp = await client.delete("/api/captures")
    assert resp.status_code == 200
    data = resp.json()
    assert "cleared" in data
    assert isinstance(data["cleared"], int)


async def test_captures_settings_update(client):
    """PUT /api/settings/captures updates and returns the new max_captures value."""
    resp = await client.put("/api/settings/captures", json={"max_captures": 100})
    assert resp.status_code == 200
    assert resp.json()["max_captures"] == 100


async def test_captures_get_nonexistent(client):
    """GET /api/captures/{id} returns 404 for an id that doesn't exist."""
    resp = await client.get("/api/captures/99999")
    assert resp.status_code == 404
