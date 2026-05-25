"""Gesture matching engine using Dynamic Time Warping (DTW).

Preprocesses raw gesture paths and compares them against stored gesture
samples to recognise wand gestures in real-time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from magicwand.config import MatchingConfig
from magicwand.detection import DetectionResult
from magicwand.gestures import GesturePoint, GestureSample, GestureStore

if TYPE_CHECKING:
    from magicwand.captures import CaptureStore


# ---------------------------------------------------------------------------
# Preprocessing functions
# ---------------------------------------------------------------------------


def resample(
    points: list[tuple[float, float]], n: int
) -> list[tuple[float, float]]:
    """Resample *points* to *n* equally-spaced points by arc-length.

    If there are fewer than 2 points, the list is padded (repeating the
    last point) to reach length *n*.
    """
    if len(points) < 2:
        if not points:
            return [(0.0, 0.0)] * n
        return [points[0]] * n

    # Compute cumulative arc-length distances
    dists = [0.0]
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        dists.append(dists[-1] + math.hypot(dx, dy))

    total_length = dists[-1]
    if total_length == 0.0:
        return [points[0]] * n

    interval = total_length / (n - 1)
    resampled: list[tuple[float, float]] = [points[0]]
    j = 1  # index into original points

    for i in range(1, n - 1):
        target_dist = i * interval
        # Advance j until dists[j] >= target_dist
        while j < len(dists) and dists[j] < target_dist:
            j += 1
        if j >= len(points):
            j = len(points) - 1
        # Interpolate between points[j-1] and points[j]
        seg_start = dists[j - 1]
        seg_end = dists[j]
        seg_len = seg_end - seg_start
        if seg_len == 0.0:
            t = 0.0
        else:
            t = (target_dist - seg_start) / seg_len
        x = points[j - 1][0] + t * (points[j][0] - points[j - 1][0])
        y = points[j - 1][1] + t * (points[j][1] - points[j - 1][1])
        resampled.append((x, y))

    resampled.append(points[-1])
    return resampled


def center(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Subtract centroid from all points so the path is centered at (0, 0)."""
    n = len(points)
    if n == 0:
        return points
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    return [(p[0] - cx, p[1] - cy) for p in points]


def normalize_scale(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Scale so the max bounding-box dimension equals 1.0.

    If all points are identical (max dimension is 0), returns as-is.
    """
    if not points:
        return points
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    max_dim = max(width, height)
    if max_dim == 0.0:
        return points
    return [(p[0] / max_dim, p[1] / max_dim) for p in points]


def rotate_to_indicative_angle(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Rotate all points so the angle from centroid to the first point is -pi/2 (up).

    Assumes points are already centered (centroid at origin).
    """
    if not points:
        return points
    # Current angle from origin to first point
    angle = math.atan2(points[0][1], points[0][0])
    # We want this angle to become -pi/2
    rotation = -math.pi / 2 - angle
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    return [
        (p[0] * cos_r - p[1] * sin_r, p[0] * sin_r + p[1] * cos_r)
        for p in points
    ]


def preprocess(
    gesture_points: list[GesturePoint], num_points: int = 32
) -> list[tuple[float, float]]:
    """Full preprocessing pipeline: resample, center, scale, rotate.

    Accepts raw GesturePoints (with normalised x, y in [0, 1]) and returns
    a list of (x, y) tuples ready for DTW comparison.
    """
    raw = [(pt.x, pt.y) for pt in gesture_points]
    pts = resample(raw, num_points)
    pts = center(pts)
    pts = normalize_scale(pts)
    pts = rotate_to_indicative_angle(pts)
    return pts


# ---------------------------------------------------------------------------
# Dwell trimming
# ---------------------------------------------------------------------------


def trim_dwells(
    points: list[GesturePoint], speed_threshold: float = 0.05
) -> list[GesturePoint]:
    """Remove near-stationary points from the start and end of a gesture.

    Speed is measured as Euclidean distance / time delta between consecutive
    points (in normalized coordinates per second). Points below the threshold
    are considered "dwelling."
    """
    if len(points) < 2:
        return points

    # Compute speeds between consecutive points (len - 1 values).
    # speeds[i] is the speed between points[i] and points[i+1].
    speeds: list[float] = []
    for i in range(len(points) - 1):
        dx = points[i + 1].x - points[i].x
        dy = points[i + 1].y - points[i].y
        dt = points[i + 1].t - points[i].t
        if dt == 0.0:
            speeds.append(0.0)
        else:
            speeds.append(math.hypot(dx, dy) / dt)

    # Trim from start: find the first index where speed >= threshold.
    # speeds[i] corresponds to the segment starting at points[i], so
    # the first "moving" point is the one whose outgoing speed is above
    # the threshold.
    first_moving = 0
    for i in range(len(speeds)):
        if speeds[i] >= speed_threshold:
            first_moving = i
            break
    else:
        # All speeds below threshold — don't over-trim
        return points

    # Trim from end: find the last index where speed >= threshold.
    # speeds[i] is the segment between points[i] and points[i+1], so
    # the last "moving" point is points[i+1] for the last fast segment.
    last_moving = len(points) - 1
    for i in range(len(speeds) - 1, -1, -1):
        if speeds[i] >= speed_threshold:
            last_moving = i + 1
            break

    # Ensure first_moving <= last_moving
    if first_moving > last_moving:
        return points

    trimmed = points[first_moving : last_moving + 1]

    # If the result would have fewer than 2 points, return the original
    if len(trimmed) < 2:
        return points

    return trimmed


# ---------------------------------------------------------------------------
# DTW
# ---------------------------------------------------------------------------


def dtw_distance(
    a: list[tuple[float, float]], b: list[tuple[float, float]]
) -> float:
    """Compute the normalised DTW distance between two preprocessed paths.

    Uses a full cost matrix with Euclidean point distance.
    Returns cost[n][m] / (n + m) for scale-independent comparison.
    """
    n = len(a)
    m = len(b)
    if n == 0 or m == 0:
        return float("inf")

    # Build cost matrix (n+1) x (m+1) initialized to infinity
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dx = a[i - 1][0] - b[j - 1][0]
            dy = a[i - 1][1] - b[j - 1][1]
            d = math.hypot(dx, dy)
            cost[i][j] = d + min(
                cost[i - 1][j], cost[i][j - 1], cost[i - 1][j - 1]
            )

    return cost[n][m] / (n + m)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """Outcome of a gesture-match attempt."""

    matched: bool
    gesture_name: str | None
    confidence: float  # 0-1
    distance: float
    all_scores: dict[str, float] = field(default_factory=dict)


class WatcherState(Enum):
    IDLE = "idle"
    TRACKING = "tracking"
    COOLDOWN = "cooldown"


# ---------------------------------------------------------------------------
# GestureWatcher
# ---------------------------------------------------------------------------


class GestureWatcher:
    """Monitors the detection stream for completed gestures and matches them.

    State machine: IDLE -> TRACKING -> (match attempt) -> COOLDOWN -> IDLE
    """

    def __init__(
        self,
        gesture_store: GestureStore,
        config: MatchingConfig,
        capture_store: CaptureStore | None = None,
    ) -> None:
        self._store = gesture_store
        self._config = config
        self._capture_store = capture_store
        self._state = WatcherState.IDLE
        self._points: list[GesturePoint] = []
        self._last_detection_time: float = 0.0
        self._tracking_start_time: float = 0.0
        self._cooldown_until: float = 0.0
        self._last_match: MatchResult | None = None
        self._preprocessed_cache: dict[str, list[list[tuple[float, float]]]] = {}

    # -- Public API ----------------------------------------------------------

    def feed(
        self,
        detection: DetectionResult,
        timestamp: float,
        frame_width: int,
        frame_height: int,
    ) -> MatchResult | None:
        """Feed a detection result from the current frame.

        Returns a MatchResult only when a gesture has been completed and a
        match attempt has been made (whether successful or not).
        """
        if self._state == WatcherState.COOLDOWN:
            if timestamp >= self._cooldown_until:
                self._state = WatcherState.IDLE
            else:
                return None

        if self._state == WatcherState.IDLE:
            if detection.detected and detection.position is not None:
                self._state = WatcherState.TRACKING
                self._points = []
                self._tracking_start_time = timestamp
                self._last_detection_time = timestamp
                # Append first point (normalised)
                nx = detection.position[0] / frame_width
                ny = detection.position[1] / frame_height
                self._points.append(GesturePoint(x=nx, y=ny, t=0.0))
            return None

        # TRACKING state
        if detection.detected and detection.position is not None:
            self._last_detection_time = timestamp
            nx = detection.position[0] / frame_width
            ny = detection.position[1] / frame_height
            t = timestamp - self._tracking_start_time
            self._points.append(GesturePoint(x=nx, y=ny, t=t))
            return None

        # Tip not detected while tracking — check gap timeout
        gap = timestamp - self._last_detection_time
        if gap >= self._config.gap_timeout:
            # Gesture complete
            result = self._attempt_match()
            self._last_match = result
            self._state = WatcherState.COOLDOWN
            self._cooldown_until = timestamp + self._config.cooldown_time
            self._points = []
            return result

        # Brief loss — keep tracking (flicker tolerance)
        return None

    def _attempt_match(self) -> MatchResult:
        """Preprocess captured points and match against stored gestures."""
        # Too few points — reject
        if len(self._points) < self._config.min_gesture_points:
            result = MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=float("inf"),
                all_scores={},
            )
            if self._capture_store:
                self._capture_store.add(self._points, result, 0)
            return result

        # Dwell trimming — remove near-stationary clusters at start/end
        if self._config.dwell_trim_enabled:
            trimmed = trim_dwells(self._points, self._config.dwell_speed_threshold)
            trimmed_count = len(self._points) - len(trimmed)
            points_for_matching = trimmed
        else:
            trimmed_count = 0
            points_for_matching = self._points

        captured = preprocess(points_for_matching, self._config.resample_count)

        all_scores: dict[str, float] = {}

        for gesture_name in self._store.list():
            samples = self._get_preprocessed_samples(gesture_name)
            if not samples:
                continue
            best_dist = float("inf")
            for sample in samples:
                d = dtw_distance(captured, sample)
                if d < best_dist:
                    best_dist = d
            all_scores[gesture_name] = best_dist

        if not all_scores:
            result = MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=float("inf"),
                all_scores=all_scores,
            )
            if self._capture_store:
                self._capture_store.add(self._points, result, trimmed_count)
            return result

        # Sort gestures by distance
        ranked = sorted(all_scores.items(), key=lambda kv: kv[1])
        best_name, best_dist = ranked[0]

        # Distance threshold check
        if best_dist > self._config.distance_threshold:
            result = MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=best_dist,
                all_scores=all_scores,
            )
            if self._capture_store:
                self._capture_store.add(self._points, result, trimmed_count)
            return result

        # Compute confidence
        confidence = 1.0 - (best_dist / self._config.distance_threshold)
        confidence = max(0.0, min(1.0, confidence))

        # Minimum confidence check
        if confidence < self._config.min_confidence:
            result = MatchResult(
                matched=False,
                gesture_name=None,
                confidence=confidence,
                distance=best_dist,
                all_scores=all_scores,
            )
            if self._capture_store:
                self._capture_store.add(self._points, result, trimmed_count)
            return result

        # Ambiguity check: reject if 2nd best is within 20% of best
        if len(ranked) >= 2:
            _second_name, second_dist = ranked[1]
            if best_dist > 0:
                ratio = (second_dist - best_dist) / best_dist
                if ratio < 0.20:
                    result = MatchResult(
                        matched=False,
                        gesture_name=None,
                        confidence=confidence,
                        distance=best_dist,
                        all_scores=all_scores,
                    )
                    if self._capture_store:
                        self._capture_store.add(self._points, result, trimmed_count)
                    return result
            else:
                # best_dist == 0 — only ambiguous if second is also 0
                if second_dist == 0:
                    result = MatchResult(
                        matched=False,
                        gesture_name=None,
                        confidence=confidence,
                        distance=best_dist,
                        all_scores=all_scores,
                    )
                    if self._capture_store:
                        self._capture_store.add(self._points, result, trimmed_count)
                    return result

        # Match!
        result = MatchResult(
            matched=True,
            gesture_name=best_name,
            confidence=confidence,
            distance=best_dist,
            all_scores=all_scores,
        )
        if self._capture_store:
            self._capture_store.add(self._points, result, trimmed_count)
        return result

    def invalidate_cache(self, gesture_name: str | None = None) -> None:
        """Clear the preprocessed sample cache.

        If *gesture_name* is provided, only that gesture's cache is cleared;
        otherwise the entire cache is dropped.
        """
        if gesture_name is None:
            self._preprocessed_cache.clear()
        else:
            self._preprocessed_cache.pop(gesture_name, None)

    @property
    def state(self) -> WatcherState:
        """Current watcher state."""
        return self._state

    @property
    def last_match(self) -> MatchResult | None:
        """The most recent match result, or None if no match has been attempted."""
        return self._last_match

    # -- Internal helpers ----------------------------------------------------

    def _get_preprocessed_samples(
        self, gesture_name: str
    ) -> list[list[tuple[float, float]]]:
        """Return preprocessed samples for *gesture_name*, using cache."""
        if gesture_name in self._preprocessed_cache:
            return self._preprocessed_cache[gesture_name]

        gesture = self._store.get(gesture_name)
        if gesture is None or not gesture.samples:
            return []

        preprocessed: list[list[tuple[float, float]]] = []
        for sample in gesture.samples:
            preprocessed.append(preprocess(sample, self._config.resample_count))

        self._preprocessed_cache[gesture_name] = preprocessed
        return preprocessed
