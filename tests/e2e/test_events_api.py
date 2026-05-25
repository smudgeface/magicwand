"""End-to-end tests for the /api/logs event log endpoint."""

from __future__ import annotations

import pytest


async def test_logs_endpoint_returns_list(client):
    """GET /api/logs returns a list (may have system_start event)."""
    resp = await client.get("/api/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


async def test_logs_endpoint_has_system_start(client):
    """The app emits system_start on startup, so logs should contain it."""
    resp = await client.get("/api/logs")
    data = resp.json()
    types = [e["type"] for e in data]
    assert "system_start" in types


async def test_logs_endpoint_limit(client):
    """Limit parameter caps results."""
    resp = await client.get("/api/logs?limit=1")
    data = resp.json()
    assert len(data) <= 1


async def test_logs_endpoint_type_filter(client):
    """Type filter works."""
    resp = await client.get("/api/logs?type=system_start")
    data = resp.json()
    for event in data:
        assert event["type"] == "system_start"
