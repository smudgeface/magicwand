"""Configuration loading from TOML using stdlib tomllib (Python 3.11+)."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass
class MockCameraConfig:
    dot_speed: float = 2.0


@dataclass
class CameraConfig:
    width: int = 640
    height: int = 480
    fps: int = 30
    source: str = "mock"
    mock: MockCameraConfig = field(default_factory=MockCameraConfig)


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)


def _load_config(path: Path | None) -> Config:
    """Load and parse a config.toml file into a Config dataclass.

    If path is None or does not exist, returns all-default config.
    """
    if path is None or not path.exists():
        logging.getLogger(__name__).info(
            "No config file at %s — using defaults", path
        )
        return Config()

    with path.open("rb") as f:
        raw = tomllib.load(f)

    server_raw = raw.get("server", {})
    server = ServerConfig(
        host=server_raw.get("host", "0.0.0.0"),
        port=server_raw.get("port", 8000),
    )

    camera_raw = raw.get("camera", {})
    mock_raw = camera_raw.get("mock", {})
    mock = MockCameraConfig(
        dot_speed=mock_raw.get("dot_speed", 2.0),
    )
    camera = CameraConfig(
        width=camera_raw.get("width", 640),
        height=camera_raw.get("height", 480),
        fps=camera_raw.get("fps", 30),
        source=camera_raw.get("source", "mock"),
        mock=mock,
    )

    return Config(server=server, camera=camera)


_cached_config: Config | None = None


def get_config(config_path: Path | str | None = None) -> Config:
    """Return the cached Config, loading it on first call.

    Args:
        config_path: Optional path to override the default config file location.
                     Useful for testing. Clears the cache and reloads when provided.
    """
    global _cached_config

    if config_path is not None:
        _cached_config = _load_config(Path(config_path))
        return _cached_config

    if _cached_config is None:
        env_path = os.environ.get("MAGICWAND_CONFIG")
        if env_path:
            path = Path(env_path)
        else:
            path = Path.cwd() / "config.toml"
        _cached_config = _load_config(path)

    return _cached_config


def clear_config_cache() -> None:
    """Clear the cached config. Useful for testing."""
    global _cached_config
    _cached_config = None
