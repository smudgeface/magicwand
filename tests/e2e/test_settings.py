import pytest


async def test_admin_page_loads(client):
    """Admin page serves correctly."""
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert "Admin" in resp.text
    assert "Detection" in resp.text
    assert "Matching" in resp.text
    assert "System" in resp.text


async def test_system_info_endpoint(client):
    """System info API returns expected keys."""
    resp = await client.get("/api/system/info")
    assert resp.status_code == 200
    data = resp.json()
    expected_keys = {"uptime_seconds", "cpu_temp_c", "ram_used_mb", "ram_total_mb",
                     "disk_used_gb", "disk_total_gb", "camera_source",
                     "detection_fps", "python_version", "app_version"}
    assert expected_keys.issubset(set(data.keys()))


async def test_system_info_uptime_positive(client):
    """Uptime should be positive."""
    resp = await client.get("/api/system/info")
    data = resp.json()
    assert data["uptime_seconds"] >= 0


async def test_system_info_app_version(client):
    """App version matches package version."""
    resp = await client.get("/api/system/info")
    data = resp.json()
    assert data["app_version"] == "0.1.0"


async def test_nav_has_admin_link(client):
    """All pages should have admin link in nav."""
    resp = await client.get("/")
    assert "/admin" in resp.text


async def test_settings_js_serves(client):
    """Settings JS file is accessible."""
    resp = await client.get("/static/js/settings.js")
    assert resp.status_code == 200
