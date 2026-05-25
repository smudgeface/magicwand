from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from magicwand.config import DetectionConfig


@dataclass
class DetectionResult:
    detected: bool
    position: tuple[int, int] | None
    confidence: float
    contour_area: float


@dataclass
class TrailPoint:
    x: int
    y: int
    timestamp: float


class FPSCounter:
    """Rolling window FPS calculator using the last 30 frame timestamps."""

    def __init__(self, window_size: int = 30) -> None:
        self._timestamps: deque[float] = deque(maxlen=window_size)

    def tick(self) -> None:
        self._timestamps.append(time.monotonic())

    @property
    def fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / elapsed


class Detector:
    """Detects the brightest IR point in a frame and renders a debug overlay."""

    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._trail: deque[TrailPoint] = deque(maxlen=config.trail_length)
        self._fps_counter = FPSCounter()

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, DetectionResult]:
        """Run detection on frame, return annotated frame + result."""
        self._fps_counter.tick()

        # Work on a copy so the original is untouched
        output = frame.copy()

        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Gaussian blur
        k = self._config.blur_kernel
        blurred = cv2.GaussianBlur(gray, (k, k), 0)

        # Binary threshold
        _, binary = cv2.threshold(
            blurred, self._config.threshold, 255, cv2.THRESH_BINARY
        )

        # Find contours
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Filter by area
        valid = [
            c
            for c in contours
            if self._config.min_area <= cv2.contourArea(c) <= self._config.max_area
        ]

        if valid:
            # Pick the largest contour
            largest = max(valid, key=cv2.contourArea)
            area = cv2.contourArea(largest)

            # Compute centroid via moments
            m = cv2.moments(largest)
            if m["m00"] > 0:
                cx = int(m["m10"] / m["m00"])
                cy = int(m["m01"] / m["m00"])
            else:
                cx, cy = 0, 0

            # Confidence: peak brightness at centroid in grayscale / 255
            confidence = float(gray[cy, cx]) / 255.0

            # Append to trail
            self._trail.append(TrailPoint(x=cx, y=cy, timestamp=time.monotonic()))

            result = DetectionResult(
                detected=True,
                position=(cx, cy),
                confidence=confidence,
                contour_area=area,
            )
        else:
            result = DetectionResult(
                detected=False,
                position=None,
                confidence=0.0,
                contour_area=0.0,
            )

        # Render overlay
        self._render_overlay(output, result)

        return output, result

    @property
    def trail(self) -> list[TrailPoint]:
        """Current trail points (most recent last)."""
        return list(self._trail)

    @property
    def fps(self) -> float:
        """Current frames-per-second."""
        return self._fps_counter.fps

    def update_config(self, **kwargs: object) -> None:
        """Update config fields dynamically."""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        # Update trail deque maxlen if trail_length changed
        if "trail_length" in kwargs:
            new_len = self._config.trail_length
            old_points = list(self._trail)
            self._trail = deque(old_points[-new_len:], maxlen=new_len)

    def _render_overlay(
        self, frame: np.ndarray, result: DetectionResult
    ) -> None:
        """Draw debug overlay onto the frame."""
        h, w = frame.shape[:2]

        # Green dot at detected position
        if result.detected and result.position is not None:
            cv2.circle(frame, result.position, 6, (0, 255, 0), -1)

        # Trail: line segments with color fading from dim to bright green
        trail_points = list(self._trail)
        n = len(trail_points)
        if n >= 2:
            for i in range(n - 1):
                # Interpolate color from (0, 60, 0) at oldest to (0, 255, 0) at newest
                t = i / (n - 1)
                green_val = int(60 + t * (255 - 60))
                color = (0, green_val, 0)
                pt1 = (trail_points[i].x, trail_points[i].y)
                pt2 = (trail_points[i + 1].x, trail_points[i + 1].y)
                cv2.line(frame, pt1, pt2, color, 2)

        # FPS: top-left, white
        fps_text = f"{self._fps_counter.fps:.1f} FPS"
        cv2.putText(
            frame, fps_text, (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )

        # Confidence: top-right
        if result.detected:
            conf_text = f"conf: {result.confidence:.2f}"
            if result.confidence > 0.6:
                conf_color = (0, 255, 0)
            elif result.confidence >= 0.3:
                conf_color = (0, 255, 255)
            else:
                conf_color = (0, 0, 255)
        else:
            conf_text = "no detection"
            conf_color = (128, 128, 128)

        # Measure text to right-align
        (tw, _), _ = cv2.getTextSize(
            conf_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        cv2.putText(
            frame, conf_text, (w - tw - 10, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, conf_color, 1,
        )

        # Threshold: bottom-left, dim gray
        thr_text = f"thr: {self._config.threshold}"
        cv2.putText(
            frame, thr_text, (10, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1,
        )

        # Status: bottom-right
        if result.detected:
            status_text = "TRACKING"
            status_color = (0, 255, 0)
        else:
            status_text = "SEARCHING"
            status_color = (0, 255, 255)

        (tw, _), _ = cv2.getTextSize(
            status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        cv2.putText(
            frame, status_text, (w - tw - 10, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1,
        )
