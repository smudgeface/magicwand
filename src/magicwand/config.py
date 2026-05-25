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
    source: str = "auto"
    mock: MockCameraConfig = field(default_factory=MockCameraConfig)
    webcam_device: int = 0
    webcam_exposure: float | None = None


@dataclass
class DetectionConfig:
    threshold: int = 240
    min_area: int = 20
    max_area: int = 5000
    blur_kernel: int = 5
    trail_length: int = 50


@dataclass
class GesturesConfig:
    directory: str = "gestures"


@dataclass
class MatchingConfig:
    distance_threshold: float = 2.0
    min_confidence: float = 0.6
    gap_timeout: float = 0.5
    cooldown_time: float = 2.0
    min_gesture_points: int = 10
    resample_count: int = 32
    dwell_speed_threshold: float = 0.05
    dwell_min_points: int = 3
    linearity_threshold: float = 0.85
    min_curvature: float = 1.57
    min_segment_duration: float = 0.2


@dataclass
class CapturesConfig:
    directory: str = "captures"
    max_captures: int = 200


@dataclass
class HomebridgePreset:
    name: str = ""
    method: str = "GET"
    url_template: str = ""


@dataclass
class HomebridgeConfig:
    host: str = "homebridge.local"
    port: int = 8581
    presets: list[HomebridgePreset] = field(default_factory=list)


@dataclass
class LoggingConfig:
    directory: str = "logs"
    max_file_size: int = 10_000_000
    max_files: int = 5


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    gestures: GesturesConfig = field(default_factory=GesturesConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    captures: CapturesConfig = field(default_factory=CapturesConfig)
    homebridge: HomebridgeConfig = field(default_factory=HomebridgeConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


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
    webcam_exposure_raw = camera_raw.get("webcam_exposure")
    camera = CameraConfig(
        width=camera_raw.get("width", 640),
        height=camera_raw.get("height", 480),
        fps=camera_raw.get("fps", 30),
        source=camera_raw.get("source", "auto"),
        mock=mock,
        webcam_device=camera_raw.get("webcam_device", 0),
        webcam_exposure=float(webcam_exposure_raw) if webcam_exposure_raw is not None else None,
    )

    detection_raw = raw.get("detection", {})
    detection = DetectionConfig(
        threshold=detection_raw.get("threshold", 240),
        min_area=detection_raw.get("min_area", 20),
        max_area=detection_raw.get("max_area", 5000),
        blur_kernel=detection_raw.get("blur_kernel", 5),
        trail_length=detection_raw.get("trail_length", 50),
    )

    gestures_raw = raw.get("gestures", {})
    gestures = GesturesConfig(
        directory=gestures_raw.get("directory", "gestures"),
    )

    matching_raw = raw.get("matching", {})
    matching = MatchingConfig(
        distance_threshold=matching_raw.get("distance_threshold", 2.0),
        min_confidence=matching_raw.get("min_confidence", 0.6),
        gap_timeout=matching_raw.get("gap_timeout", 0.5),
        cooldown_time=matching_raw.get("cooldown_time", 2.0),
        min_gesture_points=matching_raw.get("min_gesture_points", 10),
        resample_count=matching_raw.get("resample_count", 32),
        dwell_speed_threshold=matching_raw.get("dwell_speed_threshold", 0.05),
        dwell_min_points=matching_raw.get("dwell_min_points", 3),
        linearity_threshold=matching_raw.get("linearity_threshold", 0.85),
        min_curvature=matching_raw.get("min_curvature", 1.57),
        min_segment_duration=matching_raw.get("min_segment_duration", 0.2),
    )

    captures_raw = raw.get("captures", {})
    captures = CapturesConfig(
        directory=captures_raw.get("directory", "captures"),
        max_captures=captures_raw.get("max_captures", 200),
    )

    homebridge_raw = raw.get("homebridge", {})
    homebridge_presets = [
        HomebridgePreset(
            name=p.get("name", ""),
            method=p.get("method", "GET"),
            url_template=p.get("url_template", ""),
        )
        for p in homebridge_raw.get("presets", [])
    ]
    homebridge = HomebridgeConfig(
        host=homebridge_raw.get("host", "homebridge.local"),
        port=homebridge_raw.get("port", 8581),
        presets=homebridge_presets,
    )

    logging_raw = raw.get("logging", {})
    logging_config = LoggingConfig(
        directory=logging_raw.get("directory", "logs"),
        max_file_size=logging_raw.get("max_file_size", 10_000_000),
        max_files=logging_raw.get("max_files", 5),
    )

    return Config(server=server, camera=camera, detection=detection, gestures=gestures, matching=matching, captures=captures, homebridge=homebridge, logging=logging_config)


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
