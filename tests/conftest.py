"""Shared pytest fixtures for the magicwand test suite."""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from pathlib import Path
from asgi_lifespan import LifespanManager

from magicwand.config import clear_config_cache

_MINIMAL_CONFIG_TOML = """\
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
"""


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Write a minimal valid config.toml to a temp dir and return its path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(_MINIMAL_CONFIG_TOML)
    return config_file


@pytest.fixture
def app(tmp_config: Path):
    """Create a FastAPI app using the temp config (no lifespan started)."""
    clear_config_cache()
    from magicwand.main import create_app
    a = create_app(config_path=tmp_config)
    yield a
    clear_config_cache()


@pytest_asyncio.fixture
async def client(app):
    """AsyncClient with lifespan (camera thread running) for e2e tests."""
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            yield c
