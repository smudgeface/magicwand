"""Unit tests for magicwand.detection — Detector, DetectionResult, FPSCounter."""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from magicwand.config import DetectionConfig
from magicwand.detection import Detector, DetectionResult, FPSCounter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _black_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """Return an all-black BGR frame."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _frame_with_dot(
    cx: int = 320,
    cy: int = 240,
    radius: int = 10,
    color: tuple[int, int, int] = (255, 255, 255),
    width: int = 640,
    height: int = 480,
) -> np.ndarray:
    """Return a black BGR frame with a filled circle drawn at (cx, cy)."""
    frame = _black_frame(width, height)
    cv2.circle(frame, (cx, cy), radius, color, -1)
    return frame


def _default_config(**overrides) -> DetectionConfig:
    """Return a DetectionConfig with sensible test defaults, optionally overridden."""
    cfg = DetectionConfig(
        threshold=240,
        min_area=20,
        max_area=5000,
        blur_kernel=5,
        trail_hold=5.0,
        trail_fade=5.0,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# ---------------------------------------------------------------------------
# Detection correctness
# ---------------------------------------------------------------------------

def test_detect_bright_dot() -> None:
    """A white filled circle on a black frame is detected near its centre."""
    frame = _frame_with_dot(cx=320, cy=240, radius=10)
    detector = Detector(_default_config(threshold=240))

    _, result = detector.process(frame)

    assert result.detected is True
    assert result.position is not None
    px, py = result.position
    assert abs(px - 320) <= 2, f"x off by {abs(px - 320)}px"
    assert abs(py - 240) <= 2, f"y off by {abs(py - 240)}px"
    assert result.confidence > 0.9


def test_detect_no_dot() -> None:
    """An all-black frame produces no detection."""
    frame = _black_frame()
    detector = Detector(_default_config())

    _, result = detector.process(frame)

    assert result.detected is False
    assert result.position is None


def test_detect_dim_dot_below_threshold() -> None:
    """A circle whose brightness is below the threshold is not detected."""
    # Draw a gray circle (brightness 200) on a black frame.
    # With threshold=240, gray=200 pixels won't survive the binary threshold.
    frame = _frame_with_dot(color=(200, 200, 200), radius=10)
    detector = Detector(_default_config(threshold=240))

    _, result = detector.process(frame)

    assert result.detected is False


# ---------------------------------------------------------------------------
# Area filters
# ---------------------------------------------------------------------------

def test_contour_area_filter_small() -> None:
    """A single bright pixel is filtered out by min_area=20."""
    frame = _black_frame()
    # Draw a 1×1 bright square (a single pixel-ish dot via circle radius=0)
    # cv2.circle with radius=0 draws a single pixel.
    cv2.circle(frame, (320, 240), 0, (255, 255, 255), -1)

    detector = Detector(_default_config(threshold=200, min_area=20))

    _, result = detector.process(frame)

    assert result.detected is False


def test_contour_area_filter_large() -> None:
    """A 300×300 white rectangle exceeds max_area=5000 and is filtered out."""
    frame = _black_frame()
    cv2.rectangle(frame, (50, 50), (350, 350), (255, 255, 255), -1)

    detector = Detector(_default_config(threshold=200, max_area=5000))

    _, result = detector.process(frame)

    assert result.detected is False


# ---------------------------------------------------------------------------
# Trail behaviour
# ---------------------------------------------------------------------------

def test_trail_accumulates() -> None:
    """Processing 5 frames with a dot at different positions yields 5 trail points."""
    detector = Detector(_default_config())
    positions = [(100, 100), (150, 110), (200, 120), (250, 130), (300, 140)]

    for cx, cy in positions:
        frame = _frame_with_dot(cx=cx, cy=cy, radius=10)
        detector.process(frame)

    assert len(detector.trail) == 5


def test_trail_grows_with_detections() -> None:
    """Trail accumulates points from consecutive detections."""
    detector = Detector(_default_config())
    positions = [(100, 100), (150, 110), (200, 120), (250, 130), (300, 140)]

    for cx, cy in positions:
        frame = _frame_with_dot(cx=cx, cy=cy, radius=10)
        detector.process(frame)

    assert len(detector.trail) == 5


# ---------------------------------------------------------------------------
# FPS counter
# ---------------------------------------------------------------------------

def test_fps_counter_basic() -> None:
    """FPS counter returns a positive value after enough ticks."""
    counter = FPSCounter(window_size=30)

    # Calling tick() twice is sufficient to get a non-zero FPS.
    counter.tick()
    time.sleep(0.001)
    counter.tick()

    assert counter.fps > 0.0


def test_fps_counter_zero_before_ticks() -> None:
    """FPS counter returns 0.0 before any ticks (or after only one tick)."""
    counter = FPSCounter()
    assert counter.fps == 0.0

    counter.tick()
    assert counter.fps == 0.0


# ---------------------------------------------------------------------------
# Overlay rendering
# ---------------------------------------------------------------------------

def test_overlay_renders_without_crash() -> None:
    """process() succeeds and returns a frame with the same shape as input."""
    frame = _frame_with_dot()
    detector = Detector(_default_config())

    output, result = detector.process(frame)

    assert output.shape == frame.shape


def test_overlay_frame_is_different_from_input() -> None:
    """The returned frame differs from the input because the overlay was drawn."""
    frame = _frame_with_dot()
    detector = Detector(_default_config())

    output, _ = detector.process(frame)

    # The overlay draws text and circles; the arrays cannot be identical.
    assert not np.array_equal(output, frame)


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------

def test_confidence_calculation() -> None:
    """Confidence is approximately peak_brightness / 255 at the centroid."""
    # Draw a circle with color 200 (brightness 200 in grayscale).
    # Use threshold=150 so the blob survives thresholding.
    frame = _frame_with_dot(color=(200, 200, 200), radius=10)
    detector = Detector(_default_config(threshold=150))

    _, result = detector.process(frame)

    assert result.detected is True
    # The centroid lies inside the circle; its grayscale value should be 200.
    # Allow a small tolerance for Gaussian blur spreading.
    assert abs(result.confidence - 200 / 255) < 0.05, (
        f"Expected confidence ≈ {200/255:.3f}, got {result.confidence:.3f}"
    )


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------

def test_update_config() -> None:
    """update_config() changes the specified config field on the detector."""
    detector = Detector(_default_config(threshold=240))

    detector.update_config(threshold=100)

    assert detector._config.threshold == 100


def test_update_config_ignores_unknown_keys() -> None:
    """update_config() silently ignores keys that don't exist on the config."""
    detector = Detector(_default_config())

    # Should not raise
    detector.update_config(nonexistent_field=42)

    # Original fields are untouched
    assert detector._config.threshold == 240
