"""Unit tests for magicwand.config."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from magicwand.config import (
    CameraConfig,
    Config,
    MockCameraConfig,
    ServerConfig,
    clear_config_cache,
    get_config,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure a clean config cache before and after every test."""
    clear_config_cache()
    yield
    clear_config_cache()


def _write_toml(path: Path, content: str) -> Path:
    config_file = path / "config.toml"
    config_file.write_text(content)
    return config_file


class TestLoadValidConfig:
    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Loading a fully-specified TOML returns all fields correctly."""
        cfg_path = _write_toml(
            tmp_path,
            """\
[server]
host = "192.168.1.50"
port = 9090

[camera]
width = 1280
height = 720
fps = 15
source = "mock"

[camera.mock]
dot_speed = 5.0
""",
        )

        cfg = get_config(config_path=cfg_path)

        assert isinstance(cfg, Config)
        assert cfg.server.host == "192.168.1.50"
        assert cfg.server.port == 9090
        assert cfg.camera.width == 1280
        assert cfg.camera.height == 720
        assert cfg.camera.fps == 15
        assert cfg.camera.source == "mock"
        assert cfg.camera.mock.dot_speed == 5.0


class TestMissingFileReturnsDefaults:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        """Passing a nonexistent path yields an all-defaults Config."""
        nonexistent = tmp_path / "does_not_exist.toml"

        cfg = get_config(config_path=nonexistent)

        assert isinstance(cfg, Config)
        # Server defaults
        assert cfg.server == ServerConfig()
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 8000
        # Camera defaults
        assert cfg.camera == CameraConfig()
        assert cfg.camera.width == 640
        assert cfg.camera.height == 480
        assert cfg.camera.fps == 30
        assert cfg.camera.source == "auto"
        assert cfg.camera.mock.dot_speed == 2.0


class TestPartialConfig:
    def test_partial_config_server_only(self, tmp_path: Path) -> None:
        """A TOML with only [server] still yields camera defaults."""
        cfg_path = _write_toml(
            tmp_path,
            """\
[server]
host = "10.0.0.1"
port = 7777
""",
        )

        cfg = get_config(config_path=cfg_path)

        assert cfg.server.host == "10.0.0.1"
        assert cfg.server.port == 7777
        # Camera fields should all be at their defaults
        assert cfg.camera.width == 640
        assert cfg.camera.height == 480
        assert cfg.camera.fps == 30
        assert cfg.camera.source == "auto"
        assert cfg.camera.mock.dot_speed == 2.0


class TestEnvVarOverride:
    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """MAGICWAND_CONFIG env var is used when no explicit path is given."""
        cfg_path = _write_toml(
            tmp_path,
            """\
[server]
port = 5555
""",
        )

        monkeypatch.setenv("MAGICWAND_CONFIG", str(cfg_path))
        # No explicit config_path — should pick up from env var
        cfg = get_config()

        assert cfg.server.port == 5555
        # Camera should still be at defaults
        assert cfg.camera.width == 640
