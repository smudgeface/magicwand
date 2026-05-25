"""Unit tests for gesture segmentation: dwell detection, linearity, curvature, filtering."""

from __future__ import annotations

import math

import pytest

from magicwand.gestures import GesturePoint
from magicwand.matching import (
    Segment,
    compute_speeds,
    extract_gesture_candidates,
    linearity,
    segment_at_dwells,
    total_curvature,
)


def _make_dwell(n: int, x: float = 0.5, y: float = 0.5, start_t: float = 0.0) -> list[GesturePoint]:
    """Make n stationary points (speed = 0)."""
    return [GesturePoint(x=x, y=y, t=start_t + i * 0.033) for i in range(n)]


def _make_line_motion(n: int, start_x: float = 0.1, start_t: float = 0.0) -> list[GesturePoint]:
    """Make n points moving rightward (linear, high speed)."""
    return [GesturePoint(x=start_x + i * 0.05, y=0.5, t=start_t + i * 0.033) for i in range(n)]


def _make_circle_motion(n: int, start_t: float = 0.0) -> list[GesturePoint]:
    """Make n points along a circle (curved, high speed)."""
    return [
        GesturePoint(
            x=0.5 + 0.2 * math.cos(2 * math.pi * i / n),
            y=0.5 + 0.2 * math.sin(2 * math.pi * i / n),
            t=start_t + i * 0.033,
        )
        for i in range(n)
    ]


class TestComputeSpeeds:
    def test_stationary(self):
        pts = _make_dwell(5)
        speeds = compute_speeds(pts)
        assert all(s == pytest.approx(0.0) for s in speeds)

    def test_moving(self):
        pts = _make_line_motion(5)
        speeds = compute_speeds(pts)
        assert all(s > 1.0 for s in speeds)


class TestSegmentAtDwells:
    def test_dwell_motion_dwell(self):
        """Classic pattern: dwell → motion → dwell produces 3 segments."""
        pts = _make_dwell(5) + _make_line_motion(20, start_t=5 * 0.033) + _make_dwell(5, start_t=(5 + 20) * 0.033)
        segments = segment_at_dwells(pts, speed_threshold=50.0, min_dwell_points=3)
        dwell_segs = [s for s in segments if s.is_dwell]
        motion_segs = [s for s in segments if not s.is_dwell]
        assert len(dwell_segs) >= 2
        assert len(motion_segs) >= 1

    def test_all_moving(self):
        """All moving points = one non-dwell segment."""
        pts = _make_line_motion(30)
        segments = segment_at_dwells(pts, speed_threshold=50.0, min_dwell_points=3)
        non_dwell = [s for s in segments if not s.is_dwell]
        assert len(non_dwell) == 1

    def test_short_dwell_merged_into_motion(self):
        """A brief pause (< min_dwell_points) mid-gesture merges into motion."""
        motion1 = _make_line_motion(15, start_x=0.1, start_t=0.0)
        brief_pause = _make_dwell(2, x=0.85, start_t=15 * 0.033)
        motion2 = _make_line_motion(15, start_x=0.85, start_t=17 * 0.033)
        pts = motion1 + brief_pause + motion2
        segments = segment_at_dwells(pts, speed_threshold=50.0, min_dwell_points=5)
        motion_segs = [s for s in segments if not s.is_dwell]
        assert len(motion_segs) == 1
        assert len(motion_segs[0].points) >= 30


class TestLinearity:
    def test_straight_line_is_linear(self):
        pts = _make_line_motion(20)
        assert linearity(pts) > 0.95

    def test_circle_is_not_linear(self):
        pts = _make_circle_motion(30)
        assert linearity(pts) < 0.7


class TestTotalCurvature:
    def test_straight_low_curvature(self):
        pts = _make_line_motion(20)
        assert total_curvature(pts) < 0.3

    def test_circle_high_curvature(self):
        pts = _make_circle_motion(40)
        curv = total_curvature(pts)
        assert curv > 5.0  # close to 2π


class TestExtractGestureCandidates:
    def test_filters_linear_keeps_circular(self):
        """Entry trail (linear) + dwell + gesture (circle) + dwell + exit trail (linear)"""
        entry = _make_line_motion(15, start_x=0.0, start_t=0.0)
        dwell1 = _make_dwell(5, x=0.75, y=0.5, start_t=15 * 0.033)
        gesture = _make_circle_motion(40, start_t=20 * 0.033)
        dwell2 = _make_dwell(5, x=0.5, y=0.5, start_t=60 * 0.033)
        exit_trail = _make_line_motion(15, start_x=0.5, start_t=65 * 0.033)

        all_pts = entry + dwell1 + gesture + dwell2 + exit_trail
        candidates = extract_gesture_candidates(
            all_pts,
            speed_threshold=50.0,
            min_dwell_points=3,
            min_points=10,
            min_duration=0.2,
            linearity_threshold=0.85,
            min_curvature=1.0,
        )
        # Only the circular gesture should survive
        assert len(candidates) == 1
        assert len(candidates[0]) >= 30

    def test_all_linear_no_candidates(self):
        """A straight entry/exit with no gesture yields no candidates."""
        pts = _make_dwell(5) + _make_line_motion(30, start_x=0.5, start_t=5 * 0.033) + _make_dwell(5, x=0.5 + 30 * 0.05, start_t=35 * 0.033)
        candidates = extract_gesture_candidates(pts, min_curvature=1.0)
        assert len(candidates) == 0

    def test_complex_gesture_survives(self):
        """A standalone circular gesture with no dwells passes all filters."""
        pts = _make_circle_motion(50)
        candidates = extract_gesture_candidates(pts, min_points=10, min_curvature=1.0)
        assert len(candidates) == 1
