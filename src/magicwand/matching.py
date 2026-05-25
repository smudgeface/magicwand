"""Gesture matching engine using Dynamic Time Warping (DTW).

Preprocesses raw gesture paths and compares them against stored gesture
samples to recognise wand gestures in real-time.
"""

from __future__ import annotations

import math
import time
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
# Gesture segmentation
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    points: list[GesturePoint]
    is_dwell: bool
    avg_speed: float


def compute_speeds(points: list[GesturePoint], frame_width: int = 640) -> list[float]:
    """Compute speed between consecutive points in pixels/sec.

    Points have x, y in [0, 1] normalized coordinates. Multiplying by
    frame_width converts to pixel distance so the threshold is intuitive.

    Returns a list of len(points)-1 speeds.
    """
    speeds = []
    for i in range(len(points) - 1):
        dx = (points[i + 1].x - points[i].x) * frame_width
        dy = (points[i + 1].y - points[i].y) * frame_width
        dt = points[i + 1].t - points[i].t
        dist = math.sqrt(dx * dx + dy * dy)
        speed = dist / dt if dt > 0 else 0.0
        speeds.append(speed)
    return speeds


def segment_at_dwells(
    points: list[GesturePoint],
    speed_threshold: float,
    min_dwell_points: int,
    frame_width: int = 640,
) -> list[Segment]:
    """Split a point sequence into segments separated by dwells.

    Each point is labeled "dwelling" if speed to the next point < threshold.
    speed_threshold is in pixels/sec. Consecutive same-label points are grouped.
    """
    if len(points) < 2:
        return [Segment(points=points, is_dwell=False, avg_speed=0.0)]

    speeds = compute_speeds(points, frame_width)
    # Label each point (using speed of outgoing edge; last point inherits from prev)
    labels = [s < speed_threshold for s in speeds]
    labels.append(labels[-1] if labels else False)  # last point same as previous

    # Group into runs of same label
    segments = []
    run_start = 0
    for i in range(1, len(labels)):
        if labels[i] != labels[run_start]:
            seg_points = points[run_start:i]
            is_dwell = labels[run_start]
            seg_speeds = speeds[run_start : min(i, len(speeds))]
            avg_spd = sum(seg_speeds) / len(seg_speeds) if seg_speeds else 0.0
            segments.append(
                Segment(points=seg_points, is_dwell=is_dwell, avg_speed=avg_spd)
            )
            run_start = i
    # Final segment
    seg_points = points[run_start:]
    is_dwell = labels[run_start]
    seg_speeds = speeds[run_start : len(speeds)]
    avg_spd = sum(seg_speeds) / len(seg_speeds) if seg_speeds else 0.0
    segments.append(
        Segment(points=seg_points, is_dwell=is_dwell, avg_speed=avg_spd)
    )

    # Merge short non-dwell runs into adjacent dwells (noise/jitter within a pause).
    # Only merge if the segment is also slow — a short but fast motion is a real trail.
    merged = []
    for seg in segments:
        if (not seg.is_dwell
            and len(seg.points) < min_dwell_points
            and seg.avg_speed < speed_threshold * 2):
            seg = Segment(points=seg.points, is_dwell=True, avg_speed=seg.avg_speed)
        merged.append(seg)

    # Merge short dwell runs back into motion (brief speed jitter, not real pauses).
    # Use a low fixed threshold (3 pts ≈ 0.1s) — real pauses are longer.
    merged2 = []
    for seg in merged:
        if seg.is_dwell and len(seg.points) < 3:
            seg = Segment(points=seg.points, is_dwell=False, avg_speed=seg.avg_speed)
        merged2.append(seg)

    # Collapse adjacent same-label segments
    collapsed = [merged2[0]]
    for seg in merged2[1:]:
        if seg.is_dwell == collapsed[-1].is_dwell:
            combined_pts = collapsed[-1].points + seg.points
            combined_spd = (collapsed[-1].avg_speed + seg.avg_speed) / 2
            collapsed[-1] = Segment(
                points=combined_pts, is_dwell=seg.is_dwell, avg_speed=combined_spd
            )
        else:
            collapsed.append(seg)

    return collapsed


def linearity(points: list[GesturePoint]) -> float:
    """Compute R-squared of a linear least-squares fit. Returns 0-1 (1 = perfectly linear).

    Uses both x and y coordinates — fits a line in 2D via principal component analysis.
    R-squared = variance explained by the first principal component / total variance.
    """
    if len(points) < 3:
        return 1.0  # degenerate case, treat as linear

    xs = [p.x for p in points]
    ys = [p.y for p in points]

    # Center the data
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)

    # Covariance matrix elements
    cxx = sum((x - mx) ** 2 for x in xs) / len(xs)
    cyy = sum((y - my) ** 2 for y in ys) / len(ys)
    cxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)

    total_var = cxx + cyy
    if total_var < 1e-10:
        return 1.0  # all points same location

    # Eigenvalues of 2x2 covariance matrix
    # lambda = ((cxx+cyy) +/- sqrt((cxx-cyy)^2 + 4*cxy^2)) / 2
    discriminant = math.sqrt((cxx - cyy) ** 2 + 4 * cxy ** 2)
    lambda1 = (cxx + cyy + discriminant) / 2  # larger eigenvalue

    return lambda1 / total_var


def total_curvature(points: list[GesturePoint]) -> float:
    """Sum of absolute angle changes between consecutive direction vectors.

    Returns total curvature in radians. A straight line = 0, a full circle ~ 2*pi.
    """
    if len(points) < 3:
        return 0.0

    total = 0.0
    for i in range(1, len(points) - 1):
        # Direction vectors
        dx1 = points[i].x - points[i - 1].x
        dy1 = points[i].y - points[i - 1].y
        dx2 = points[i + 1].x - points[i].x
        dy2 = points[i + 1].y - points[i].y

        # Angle between consecutive direction vectors
        len1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
        len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)

        if len1 < 1e-10 or len2 < 1e-10:
            continue

        # Cross product gives sin(angle), dot product gives cos(angle)
        cross = dx1 * dy2 - dy1 * dx2
        dot = dx1 * dx2 + dy1 * dy2
        angle = abs(math.atan2(cross, dot))
        total += angle

    return total


def extract_gesture_candidates(
    points: list[GesturePoint],
    speed_threshold: float = 50.0,
    min_dwell_points: int = 3,
    min_points: int = 10,
    min_duration: float = 0.2,
    linearity_threshold: float = 0.95,
    min_curvature: float = 1.57,
    frame_width: int = 640,
) -> list[list[GesturePoint]]:
    """Full segmentation pipeline: segment at dwells -> filter trivial -> return candidates.

    speed_threshold is in pixels/sec.
    """

    # 1. Segment at dwells
    segments = segment_at_dwells(points, speed_threshold, min_dwell_points, frame_width)

    # 2. Collect non-dwell (motion) segments
    motion_segments = [s for s in segments if not s.is_dwell]

    # 3. Filter each motion segment
    candidates = []
    for seg in motion_segments:
        pts = seg.points

        # Too few points
        if len(pts) < min_points:
            continue

        # Too short duration
        duration = pts[-1].t - pts[0].t if len(pts) > 1 else 0
        if duration < min_duration:
            continue

        r_squared = linearity(pts)
        curvature = total_curvature(pts)
        # Near-perfect linearity means it's a straight trail — any measured
        # curvature is detection noise, not intentional direction changes.
        if r_squared > 0.98:
            continue
        # Moderately linear + low curvature = likely a trail
        if r_squared > linearity_threshold and curvature < min_curvature:
            continue

        candidates.append(pts)

    return candidates


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
        self._frame_width: int = 640

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
        self._frame_width = frame_width

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
        """Segment captured points, extract gesture candidates, and match."""
        # Extract gesture candidates using segmentation
        candidates = extract_gesture_candidates(
            self._points,
            speed_threshold=self._config.dwell_speed_threshold,
            min_dwell_points=self._config.dwell_min_points,
            min_points=self._config.min_gesture_points,
            min_duration=self._config.min_segment_duration,
            linearity_threshold=self._config.linearity_threshold,
            min_curvature=self._config.min_curvature,
            frame_width=self._frame_width,
        )

        trimmed_count = len(self._points) - sum(len(c) for c in candidates)

        if not candidates:
            result = MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=0.0,
                all_scores={},
            )
            if self._capture_store:
                self._capture_store.add(self._points, result, trimmed_count)
            self._state = WatcherState.COOLDOWN
            self._cooldown_until = time.monotonic() + self._config.cooldown_time
            return result

        # Try all candidates, keep the strongest match
        best_match: MatchResult | None = None
        best_nomatch: MatchResult | None = None
        for candidate in candidates:
            preprocessed = preprocess(candidate, self._config.resample_count)
            result = self._compare_against_store(preprocessed)
            if result.matched:
                if best_match is None or result.distance < best_match.distance:
                    best_match = result
            else:
                if best_nomatch is None or result.distance < best_nomatch.distance:
                    best_nomatch = result

        final = best_match if best_match is not None else best_nomatch
        assert final is not None
        if self._capture_store:
            self._capture_store.add(self._points, final, trimmed_count)
        return final

    def _compare_against_store(
        self, preprocessed: list[tuple[float, float]]
    ) -> MatchResult:
        """Compare a preprocessed candidate against all stored gestures.

        Applies distance threshold, confidence, and ambiguity checks.
        Returns a MatchResult.
        """
        all_scores: dict[str, float] = {}

        for gesture_name in self._store.list():
            samples = self._get_preprocessed_samples(gesture_name)
            if not samples:
                continue
            best_dist = float("inf")
            for sample in samples:
                d = dtw_distance(preprocessed, sample)
                if d < best_dist:
                    best_dist = d
            all_scores[gesture_name] = best_dist

        if not all_scores:
            return MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=float("inf"),
                all_scores=all_scores,
            )

        # Sort gestures by distance
        ranked = sorted(all_scores.items(), key=lambda kv: kv[1])
        best_name, best_dist = ranked[0]

        # Distance threshold check
        if best_dist > self._config.distance_threshold:
            return MatchResult(
                matched=False,
                gesture_name=None,
                confidence=0.0,
                distance=best_dist,
                all_scores=all_scores,
            )

        # Compute confidence
        confidence = 1.0 - (best_dist / self._config.distance_threshold)
        confidence = max(0.0, min(1.0, confidence))

        # Minimum confidence check
        if confidence < self._config.min_confidence:
            return MatchResult(
                matched=False,
                gesture_name=None,
                confidence=confidence,
                distance=best_dist,
                all_scores=all_scores,
            )

        # Ambiguity check: reject if 2nd best is within 20% of best
        if len(ranked) >= 2:
            _second_name, second_dist = ranked[1]
            if best_dist > 0:
                ratio = (second_dist - best_dist) / best_dist
                if ratio < 0.20:
                    return MatchResult(
                        matched=False,
                        gesture_name=None,
                        confidence=confidence,
                        distance=best_dist,
                        all_scores=all_scores,
                    )
            else:
                # best_dist == 0 — only ambiguous if second is also 0
                if second_dist == 0:
                    return MatchResult(
                        matched=False,
                        gesture_name=None,
                        confidence=confidence,
                        distance=best_dist,
                        all_scores=all_scores,
                    )

        # Match!
        return MatchResult(
            matched=True,
            gesture_name=best_name,
            confidence=confidence,
            distance=best_dist,
            all_scores=all_scores,
        )

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
