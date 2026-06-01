from __future__ import annotations

import math
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
    """Detects the brightest IR point and renders a debug overlay.

    Pipeline: grayscale → blur → absolute-brightness threshold → connected
    components (pixel-count areas, so single-pixel spots are detectable) →
    per-blob filtering by area, local contrast (white top-hat prominence),
    and circularity (only above ``circularity_min_area``) → pick the
    highest-scoring blob.
    """

    VIEW_MODES = ("overlay", "filtered", "raw")

    def __init__(self, config: DetectionConfig) -> None:
        self._config = config
        self._trail: list[TrailPoint] = []
        self._fps_counter = FPSCounter()
        self.view_mode: str = "overlay"
        self._last_kept: int = 0
        self._last_rejected: int = 0

    # -- public API ---------------------------------------------------------

    @property
    def trail(self) -> list[TrailPoint]:
        """Current trail points (most recent last)."""
        return list(self._trail)

    @property
    def fps(self) -> float:
        """Current frames-per-second."""
        return self._fps_counter.fps

    def set_view_mode(self, mode: str) -> bool:
        """Set the stream view mode. Returns False for an unknown mode."""
        if mode in self.VIEW_MODES:
            self.view_mode = mode
            return True
        return False

    def update_config(self, **kwargs: object) -> None:
        """Update config fields dynamically."""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, DetectionResult]:
        """Run detection on frame, return the view frame + result."""
        self._fps_counter.tick()

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        k = self._config.blur_kernel
        blurred = cv2.GaussianBlur(gray, (k, k), 0) if k and k >= 3 else gray

        # Absolute-brightness gate (unchanged meaning: a hard cutoff).
        _, binary = cv2.threshold(
            blurred, self._config.threshold, 255, cv2.THRESH_BINARY
        )

        # Local prominence ("how much brighter than the surroundings") — this
        # is the contrast / edge measure, and it works down to a single pixel.
        tophat = None
        tk = self._config.tophat_kernel
        if tk and tk >= 3:
            if tk % 2 == 0:
                tk += 1
            # MORPH_RECT (not ELLIPSE): a rectangular element uses OpenCV's
            # separable erode/dilate, which is ~order-of-magnitude cheaper on
            # the Pi Zero and just as good for estimating a smooth background.
            se = cv2.getStructuringElement(cv2.MORPH_RECT, (tk, tk))
            tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, se)

        result, kept, rejected = self._find_tip(gray, blurred, binary, tophat)
        self._last_kept = len(kept)
        self._last_rejected = len(rejected)

        if result.detected and result.position is not None:
            self._trail.append(
                TrailPoint(x=result.position[0], y=result.position[1],
                           timestamp=time.monotonic())
            )

        max_age = self._config.trail_hold + self._config.trail_fade
        now = time.monotonic()
        self._trail = [p for p in self._trail if (now - p.timestamp) < max_age]

        output = self._render(frame, binary, result, kept, rejected)
        return output, result

    # -- detection ----------------------------------------------------------

    def _find_tip(
        self,
        gray: np.ndarray,
        blurred: np.ndarray,
        binary: np.ndarray,
        tophat: np.ndarray | None,
    ) -> tuple[DetectionResult, list[dict], list[tuple]]:
        """Find candidate blobs, filter them, and pick the best one."""
        cfg = self._config
        num, labels, stats, centroids = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )

        kept: list[dict] = []
        rejected: list[tuple] = []  # (x, y, w, h) of filtered-out blobs

        for i in range(1, num):  # label 0 is the background
            area = int(stats[i, cv2.CC_STAT_AREA])
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            bbox = (x, y, w, h)

            if area < cfg.min_area or area > cfg.max_area:
                rejected.append(bbox)
                continue

            comp = labels[y:y + h, x:x + w] == i

            # Local contrast: peak top-hat (or raw brightness if disabled).
            if tophat is not None:
                contrast = int(tophat[y:y + h, x:x + w][comp].max())
            else:
                contrast = int(blurred[y:y + h, x:x + w][comp].max())
            if cfg.min_contrast > 0 and contrast < cfg.min_contrast:
                rejected.append(bbox)
                continue

            # Circularity only where it's meaningful (not for tiny spots).
            circ = 1.0
            if cfg.min_circularity > 0 and area >= cfg.circularity_min_area:
                circ = self._circularity(comp.astype(np.uint8))
                if circ < cfg.min_circularity:
                    rejected.append(bbox)
                    continue

            cx = int(round(centroids[i][0]))
            cy = int(round(centroids[i][1]))
            score = contrast * (circ if cfg.min_circularity > 0 else 1.0)
            kept.append({
                "cx": cx, "cy": cy, "area": area,
                "contrast": contrast, "circ": circ, "bbox": bbox, "score": score,
            })

        if not kept:
            return DetectionResult(False, None, 0.0, 0.0), kept, rejected

        best = max(kept, key=lambda c: c["score"])
        cx, cy = best["cx"], best["cy"]
        cyc = min(max(cy, 0), gray.shape[0] - 1)
        cxc = min(max(cx, 0), gray.shape[1] - 1)
        confidence = float(gray[cyc, cxc]) / 255.0
        result = DetectionResult(True, (cx, cy), confidence, float(best["area"]))
        return result, kept, rejected

    @staticmethod
    def _circularity(mask: np.ndarray) -> float:
        """Return 4π·area / perimeter² for the largest contour in *mask*."""
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return 0.0
        c = max(cnts, key=cv2.contourArea)
        peri = cv2.arcLength(c, True)
        if peri <= 0:
            return 0.0
        return float(4.0 * math.pi * cv2.contourArea(c) / (peri * peri))

    # -- rendering ----------------------------------------------------------

    def _render(
        self,
        frame: np.ndarray,
        binary: np.ndarray,
        result: DetectionResult,
        kept: list[dict],
        rejected: list[tuple],
    ) -> np.ndarray:
        """Build the frame to stream, depending on the active view mode."""
        if self.view_mode == "raw":
            return self._render_raw(frame)
        if self.view_mode == "filtered":
            return self._render_filtered(binary, result, kept, rejected)
        output = frame.copy()
        self._render_overlay(output, result)
        return output

    def _render_raw(self, frame: np.ndarray) -> np.ndarray:
        """Clean image with a centre crosshair for focus/aiming — no detection."""
        output = frame.copy()
        h, w = output.shape[:2]
        cx, cy = w // 2, h // 2
        gray = (120, 120, 120)
        cv2.line(output, (cx - 12, cy), (cx + 12, cy), gray, 1)
        cv2.line(output, (cx, cy - 12), (cx, cy + 12), gray, 1)
        cv2.circle(output, (cx, cy), 18, gray, 1)
        return output

    def _render_filtered(
        self,
        binary: np.ndarray,
        result: DetectionResult,
        kept: list[dict],
        rejected: list[tuple],
    ) -> np.ndarray:
        """Show what the detector sees: the mask, rejected vs selected blobs."""
        output = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        h, w = output.shape[:2]
        # Rejected blobs in red, kept in cyan, selected in green.
        for (x, y, bw, bh) in rejected:
            cv2.rectangle(output, (x - 2, y - 2), (x + bw + 2, y + bh + 2), (0, 0, 200), 1)
        for blob in kept:
            x, y, bw, bh = blob["bbox"]
            cv2.rectangle(output, (x - 2, y - 2), (x + bw + 2, y + bh + 2), (200, 200, 0), 1)
        if result.detected and result.position is not None:
            cv2.circle(output, result.position, 8, (0, 255, 0), 1)
            cv2.circle(output, result.position, 1, (0, 255, 0), -1)

        cv2.putText(output, f"{self._fps_counter.fps:.1f} FPS", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        info = f"kept {self._last_kept}  rejected {self._last_rejected}"
        cv2.putText(output, info, (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        label = "FILTERED"
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(output, label, (w - tw - 10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        return output

    def _render_overlay(self, frame: np.ndarray, result: DetectionResult) -> None:
        """Draw the normal debug overlay onto the (raw) frame."""
        h, w = frame.shape[:2]

        if result.detected and result.position is not None:
            cv2.circle(frame, result.position, 6, (0, 255, 0), -1)

        trail_points = self._trail
        now = time.monotonic()
        n = len(trail_points)
        if n >= 2:
            for i in range(n - 1):
                age = now - trail_points[i].timestamp
                if age < self._config.trail_hold:
                    alpha = 1.0
                elif self._config.trail_fade > 0:
                    alpha = 1.0 - (age - self._config.trail_hold) / self._config.trail_fade
                else:
                    alpha = 0.0
                green_val = int(255 * max(0.0, alpha))
                if green_val < 10:
                    continue
                color = (0, green_val, 0)
                pt1 = (trail_points[i].x, trail_points[i].y)
                pt2 = (trail_points[i + 1].x, trail_points[i + 1].y)
                cv2.line(frame, pt1, pt2, color, 2)

        fps_text = f"{self._fps_counter.fps:.1f} FPS"
        cv2.putText(frame, fps_text, (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

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

        (tw, _), _ = cv2.getTextSize(conf_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, conf_text, (w - tw - 10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, conf_color, 1)

        thr_text = f"thr: {self._config.threshold}"
        cv2.putText(frame, thr_text, (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)

        if result.detected:
            status_text = "TRACKING"
            status_color = (0, 255, 0)
        else:
            status_text = "SEARCHING"
            status_color = (0, 255, 255)

        (tw, _), _ = cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, status_text, (w - tw - 10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1)
