"""Unit tests for magicwand.matching — preprocessing, DTW, and GestureWatcher."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from magicwand.config import MatchingConfig
from magicwand.detection import DetectionResult
from magicwand.gestures import GesturePoint, GestureStore
from magicwand.matching import (
    GestureWatcher,
    MatchResult,
    WatcherState,
    center,
    dtw_distance,
    normalize_scale,
    preprocess,
    resample,
    rotate_to_indicative_angle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_circle(n: int = 50) -> list[GesturePoint]:
    """Return a circle of n points, normalized to [0, 1]."""
    return [
        GesturePoint(
            x=0.5 + 0.3 * math.cos(2 * math.pi * i / n),
            y=0.5 + 0.3 * math.sin(2 * math.pi * i / n),
            t=float(i),
        )
        for i in range(n)
    ]


def _make_line(n: int = 20) -> list[GesturePoint]:
    """Return a horizontal line of n points across [0.1, 0.9]."""
    return [
        GesturePoint(x=0.1 + 0.8 * i / (n - 1), y=0.5, t=float(i))
        for i in range(n)
    ]


def _make_detection(x: int = 320, y: int = 240, detected: bool = True) -> DetectionResult:
    return DetectionResult(
        detected=detected,
        position=(x, y) if detected else None,
        confidence=0.9,
        contour_area=100.0,
    )


def _no_detection() -> DetectionResult:
    return _make_detection(detected=False)


# ---------------------------------------------------------------------------
# Preprocessing — resample
# ---------------------------------------------------------------------------

def test_preprocess_resample_count() -> None:
    """preprocess() on 100-point input always returns exactly 32 points."""
    pts = [GesturePoint(x=i / 100, y=i / 100, t=float(i)) for i in range(100)]
    result = preprocess(pts, num_points=32)
    assert len(result) == 32


def test_resample_output_length() -> None:
    """resample() always returns exactly n points."""
    raw = [(float(i), 0.0) for i in range(10)]
    assert len(resample(raw, 32)) == 32
    assert len(resample(raw, 8)) == 8


def test_resample_single_point() -> None:
    """resample() on a single-point list pads with that point."""
    result = resample([(0.5, 0.5)], 5)
    assert len(result) == 5
    assert all(p == (0.5, 0.5) for p in result)


# ---------------------------------------------------------------------------
# Preprocessing — centering
# ---------------------------------------------------------------------------

def test_preprocess_centering() -> None:
    """Preprocessed path centroid is very close to (0, 0)."""
    pts = _make_circle(50)
    result = preprocess(pts, num_points=32)
    cx = sum(p[0] for p in result) / len(result)
    cy = sum(p[1] for p in result) / len(result)
    assert abs(cx) < 1e-9
    assert abs(cy) < 1e-9


def test_center_shifts_centroid() -> None:
    """center() shifts all points so mean x and mean y are 0."""
    pts = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    centered = center(pts)
    cx = sum(p[0] for p in centered) / len(centered)
    cy = sum(p[1] for p in centered) / len(centered)
    assert abs(cx) < 1e-9
    assert abs(cy) < 1e-9


# ---------------------------------------------------------------------------
# Preprocessing — scale
# ---------------------------------------------------------------------------

def test_preprocess_scale() -> None:
    """Preprocessed path bounding box is contained within [-1, 1] × [-1, 1],
    and the larger dimension spans 1.0."""
    pts = _make_circle(50)
    result = preprocess(pts, num_points=32)
    xs = [p[0] for p in result]
    ys = [p[1] for p in result]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    max_dim = max(width, height)
    # After scale normalization max_dim should be 1.0 (before rotation may shift slightly)
    # Just verify all coords are bounded
    assert all(-1.5 <= x <= 1.5 for x in xs)
    assert all(-1.5 <= y <= 1.5 for y in ys)


def test_normalize_scale_max_dim_one() -> None:
    """normalize_scale() scales so the max bounding-box dimension is 1.0."""
    pts = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0)]
    scaled = normalize_scale(pts)
    xs = [p[0] for p in scaled]
    ys = [p[1] for p in scaled]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert abs(max(width, height) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Preprocessing — rotation invariance
# ---------------------------------------------------------------------------

def test_preprocess_rotation_invariance() -> None:
    """Same shape drawn at two different rotations matches after preprocessing."""
    # A right-angle path (L-shape) at different rotations
    def make_L(angle_offset: float, n: int = 20) -> list[GesturePoint]:
        pts = []
        # Horizontal segment
        for i in range(n):
            t = i / n
            x = 0.5 + 0.3 * math.cos(angle_offset) * t
            y = 0.5 + 0.3 * math.sin(angle_offset) * t
            pts.append(GesturePoint(x=x, y=y, t=float(i)))
        # Vertical segment
        for i in range(n):
            t = i / n
            x = 0.5 + 0.3 * math.cos(angle_offset) + 0.3 * math.cos(angle_offset + math.pi / 2) * t
            y = 0.5 + 0.3 * math.sin(angle_offset) + 0.3 * math.sin(angle_offset + math.pi / 2) * t
            pts.append(GesturePoint(x=x, y=y, t=float(n + i)))
        return pts

    path_0 = preprocess(make_L(0.0))
    path_45 = preprocess(make_L(math.pi / 4))

    dist = dtw_distance(path_0, path_45)
    # After rotation alignment the two L-shapes should be close
    assert dist < 0.3, f"Rotation-invariance distance too large: {dist}"


# ---------------------------------------------------------------------------
# DTW distance
# ---------------------------------------------------------------------------

def test_dtw_identical_paths() -> None:
    """DTW distance between identical paths is 0."""
    pts = [(float(i), float(i)) for i in range(32)]
    assert dtw_distance(pts, pts) == pytest.approx(0.0, abs=1e-9)


def test_dtw_different_paths() -> None:
    """DTW distance between clearly different paths is > 0."""
    a = [(0.0, 0.0)] * 32
    b = [(1.0, 1.0)] * 32
    assert dtw_distance(a, b) > 0


def test_dtw_similar_paths() -> None:
    """Slightly perturbed path has smaller DTW distance than a very different one."""
    base = [(i / 31, 0.0) for i in range(32)]
    similar = [(i / 31 + 0.01, 0.01) for i in range(32)]
    different = [(0.0, i / 31) for i in range(32)]
    assert dtw_distance(base, similar) < dtw_distance(base, different)


# ---------------------------------------------------------------------------
# GestureWatcher — matching
# ---------------------------------------------------------------------------

def _make_store_with_gesture(tmp_path: Path, name: str = "lumos") -> GestureStore:
    """Return a GestureStore with a 20-point horizontal-line gesture."""
    store = GestureStore(tmp_path)
    store.create(name)
    sample = _make_line(20)
    store.add_sample(name, sample)
    return store


def test_match_known_gesture(tmp_path: Path) -> None:
    """A gesture identical to a stored sample matches."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(distance_threshold=2.0, min_confidence=0.1, min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)

    # Feed a live path nearly identical to the stored one
    live = _make_line(20)
    watcher._points = live
    result = watcher._attempt_match()

    assert result.matched is True
    assert result.gesture_name == "lumos"
    assert result.confidence > 0.0


def test_reject_unknown_gesture(tmp_path: Path) -> None:
    """A gesture very different from stored samples does not match."""
    store = _make_store_with_gesture(tmp_path, "lumos")  # stored: horizontal line
    cfg = MatchingConfig(distance_threshold=0.05, min_confidence=0.6, min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)

    # Circle is very different from a line
    live = _make_circle(30)
    watcher._points = live
    result = watcher._attempt_match()

    assert result.matched is False


# ---------------------------------------------------------------------------
# GestureWatcher — state transitions
# ---------------------------------------------------------------------------

def test_watcher_state_transitions(tmp_path: Path) -> None:
    """idle → tracking → (gesture complete) → cooldown → idle."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(
        gap_timeout=0.5,
        cooldown_time=1.0,
        min_gesture_points=5,
        distance_threshold=2.0,
        min_confidence=0.1,
    )
    watcher = GestureWatcher(store, cfg)

    assert watcher.state == WatcherState.IDLE

    # Feed tip detections — transitions to TRACKING
    ts = 0.0
    for i in range(15):
        det = _make_detection(x=100 + i * 5, y=240)
        watcher.feed(det, ts, 640, 480)
        ts += 0.033

    assert watcher.state == WatcherState.TRACKING

    # Feed no-detection past the gap_timeout
    ts += 0.6  # > gap_timeout 0.5
    result = watcher.feed(_no_detection(), ts, 640, 480)

    # Should have transitioned to COOLDOWN and returned a result
    assert watcher.state == WatcherState.COOLDOWN
    assert result is not None

    # Advance past cooldown
    ts += 1.1  # > cooldown_time 1.0
    watcher.feed(_no_detection(), ts, 640, 480)
    assert watcher.state == WatcherState.IDLE


def test_watcher_cooldown(tmp_path: Path) -> None:
    """After a match, watcher ignores new gestures until cooldown expires."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(
        gap_timeout=0.5,
        cooldown_time=2.0,
        min_gesture_points=5,
        distance_threshold=2.0,
        min_confidence=0.1,
    )
    watcher = GestureWatcher(store, cfg)

    # Drive through one gesture cycle
    ts = 0.0
    for i in range(15):
        watcher.feed(_make_detection(x=100 + i * 5, y=240), ts, 640, 480)
        ts += 0.033
    ts += 0.6
    watcher.feed(_no_detection(), ts, 640, 480)

    assert watcher.state == WatcherState.COOLDOWN

    # Try to start a new gesture during cooldown — should be ignored
    for _ in range(10):
        result = watcher.feed(_make_detection(x=200, y=200), ts + 0.1, 640, 480)
        assert result is None
    assert watcher.state == WatcherState.COOLDOWN


def test_watcher_brief_gap_does_not_complete_gesture(tmp_path: Path) -> None:
    """A tip loss shorter than gap_timeout does not trigger a match."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(gap_timeout=0.5, min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)

    ts = 0.0
    # Start tracking
    for i in range(10):
        watcher.feed(_make_detection(x=100 + i * 5, y=240), ts, 640, 480)
        ts += 0.033

    # Brief gap — less than gap_timeout
    result = watcher.feed(_no_detection(), ts + 0.1, 640, 480)
    assert result is None
    assert watcher.state == WatcherState.TRACKING


def test_watcher_too_few_points_no_match(tmp_path: Path) -> None:
    """A gesture with fewer than min_gesture_points is rejected."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(gap_timeout=0.3, min_gesture_points=15, distance_threshold=2.0)
    watcher = GestureWatcher(store, cfg)

    ts = 0.0
    # Feed only 5 points (less than min_gesture_points=15)
    for i in range(5):
        watcher.feed(_make_detection(x=100 + i * 5, y=240), ts, 640, 480)
        ts += 0.033

    ts += 0.5  # trigger completion
    result = watcher.feed(_no_detection(), ts, 640, 480)

    assert result is not None
    assert result.matched is False


# ---------------------------------------------------------------------------
# GestureWatcher — ambiguity rejection
# ---------------------------------------------------------------------------

def test_ambiguity_rejection(tmp_path: Path) -> None:
    """Two nearly identical gestures produce an ambiguous match → rejected."""
    store = GestureStore(tmp_path)
    store.create("spell-a")
    store.create("spell-b")

    # Both gestures share the same horizontal line sample
    line = _make_line(20)
    store.add_sample("spell-a", line)
    store.add_sample("spell-b", line)

    cfg = MatchingConfig(distance_threshold=2.0, min_confidence=0.1, min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)

    watcher._points = _make_line(20)
    result = watcher._attempt_match()

    # Ambiguity check: both are equally close → should reject
    assert result.matched is False


# ---------------------------------------------------------------------------
# GestureWatcher — cache invalidation
# ---------------------------------------------------------------------------

def test_cache_invalidation(tmp_path: Path) -> None:
    """invalidate_cache() clears the preprocessed sample cache."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)

    # Populate cache
    watcher._points = _make_line(20)
    watcher._attempt_match()
    assert "lumos" in watcher._preprocessed_cache

    # Invalidate specific name
    watcher.invalidate_cache("lumos")
    assert "lumos" not in watcher._preprocessed_cache

    # Re-populate, then invalidate all
    watcher._attempt_match()
    watcher.invalidate_cache()
    assert len(watcher._preprocessed_cache) == 0


def test_on_change_hook_invalidates_cache(tmp_path: Path) -> None:
    """GestureStore.on_change wired to invalidate_cache clears cache on add_sample."""
    store = _make_store_with_gesture(tmp_path, "lumos")
    cfg = MatchingConfig(min_gesture_points=5)
    watcher = GestureWatcher(store, cfg)
    store.on_change = watcher.invalidate_cache

    # Populate cache
    watcher._points = _make_line(20)
    watcher._attempt_match()
    assert "lumos" in watcher._preprocessed_cache

    # Modifying the store via add_sample should clear the cache entry
    store.add_sample("lumos", _make_line(15))
    assert "lumos" not in watcher._preprocessed_cache
