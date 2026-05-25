"""End-to-end tests for the magicwand FastAPI app (health, index, MJPEG stream)."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time

import httpx
import pytest
from asgi_lifespan import LifespanManager

from magicwand.config import clear_config_cache


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

async def test_health_endpoint(client: httpx.AsyncClient) -> None:
    """GET /api/health returns 200 with status 'ok' and a numeric uptime."""
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime"], (int, float))


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

async def test_index_page(client: httpx.AsyncClient) -> None:
    """GET / returns 200 HTML containing an <img> pointing at /api/stream."""
    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert "<img" in html
    assert "/api/stream" in html


# ---------------------------------------------------------------------------
# MJPEG stream
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Return an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Poll until a TCP connection succeeds or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


async def test_mjpeg_stream_returns_frames(tmp_config) -> None:
    """GET /api/stream yields MJPEG multipart data with JPEG magic bytes.

    Launches a real uvicorn process so that the ASGI streaming generator can
    actually run and push frames to a real HTTP client.  This avoids the
    buffering behaviour of the test transports (httpx ASGI / Starlette
    TestClient), which both wait for the response to finish before delivering
    any bytes — incompatible with an infinite MJPEG stream.
    """
    port = _find_free_port()
    python = sys.executable

    # Launch uvicorn in a subprocess with our temp config
    proc = subprocess.Popen(
        [
            python,
            "-c",
            (
                "import magicwand.main as m, sys;"
                f"import uvicorn;"
                f"from pathlib import Path;"
                f"app = m.create_app(config_path=Path({str(tmp_config)!r}));"
                f"uvicorn.run(app, host='127.0.0.1', port={port}, log_level='warning')"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to be ready
        server_up = _wait_for_port("127.0.0.1", port, timeout=10.0)
        assert server_up, f"uvicorn did not start on port {port} within 10 s"

        base_url = f"http://127.0.0.1:{port}"

        async with httpx.AsyncClient(base_url=base_url) as c:
            collected = b""

            async with c.stream("GET", "/api/stream") as response:
                assert response.status_code == 200
                content_type = response.headers.get("content-type", "")
                assert "multipart/x-mixed-replace" in content_type
                assert "boundary=frame" in content_type

                # Collect until we have a JPEG SOI marker or 8 KB of data.
                async def _collect() -> bytes:
                    buf = b""
                    async for chunk in response.aiter_bytes(chunk_size=512):
                        buf += chunk
                        if b"\xff\xd8\xff" in buf or len(buf) >= 8192:
                            break
                    return buf

                try:
                    collected = await asyncio.wait_for(_collect(), timeout=5.0)
                except asyncio.TimeoutError:
                    pytest.fail("Timed out waiting for MJPEG frame data (5 s)")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert b"--frame" in collected, (
        f"Expected MJPEG boundary '--frame' (got {len(collected)} bytes)"
    )
    assert b"\xff\xd8\xff" in collected, (
        f"Expected JPEG magic bytes FF D8 FF (got {len(collected)} bytes)"
    )
