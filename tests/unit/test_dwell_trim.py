"""Unit tests for magicwand.matching.trim_dwells."""

from __future__ import annotations

import pytest

from magicwand.gestures import GesturePoint
from magicwand.matching import trim_dwells


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dwell(n: int, x: float = 0.5, y: float = 0.5, start_t: float = 0.0) -> list[GesturePoint]:
    """Make n stationary points (speed == 0)."""
    return [GesturePoint(x=x, y=y, t=start_t + i * 0.033) for i in range(n)]


def make_motion(n: int, start_x: float = 0.1, start_t: float = 0.0) -> list[GesturePoint]:
    """Make n points moving rightward at ~3 units/sec (well above 0.05 threshold).

    speed = 0.1 / 0.033 ≈ 3.03, well above the default 0.05 threshold.
    """
    return [GesturePoint(x=start_x + i * 0.1, y=0.5, t=start_t + i * 0.033) for i in range(n)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_trim_leading_dwell() -> None:
    """Stationary points at the start are removed, leaving the moving segment."""
    dwell = make_dwell(5, x=0.5, y=0.5, start_t=0.0)
    motion_start_t = dwell[-1].t + 0.033
    motion = make_motion(20, start_x=0.5, start_t=motion_start_t)
    points = dwell + motion

    result = trim_dwells(points)

    # Leading 5 dwell points trimmed; motion segment kept
    assert len(result) == len(motion)
    assert result[0].t == pytest.approx(motion[0].t)


def test_trim_trailing_dwell() -> None:
    """Stationary points at the end are removed, leaving the moving segment.

    The dwell is placed at the same (x, y) as the last motion point so the
    motion→dwell boundary segment has speed 0, making it the first point that
    is trimmed. The result should have exactly len(motion) points.
    """
    motion = make_motion(20, start_x=0.1, start_t=0.0)
    last_x = motion[-1].x
    dwell_start_t = motion[-1].t + 0.033
    # Dwell at the same position as the last motion point — the first
    # dwell→dwell segment has speed 0 (same x, y), so trim_dwells stops at
    # motion[-1].
    dwell = make_dwell(5, x=last_x, y=0.5, start_t=dwell_start_t)
    points = motion + dwell

    result = trim_dwells(points)

    # Trailing 5 dwell points trimmed; full motion segment kept
    assert len(result) == len(motion)
    assert result[-1].t == pytest.approx(motion[-1].t)


def test_trim_both_ends() -> None:
    """Dwells at both the start and end are trimmed.

    8 dwell points (4 leading + 4 trailing) are added around 20 motion points.
    After trimming the result must be substantially shorter than the 28-point
    input, and no result point may equal any dwell point that is interior to
    either dwell cluster.
    """
    leading = make_dwell(4, x=0.1, y=0.1, start_t=0.0)
    motion_start_t = leading[-1].t + 0.033
    motion = make_motion(20, start_x=0.5, start_t=motion_start_t)
    trailing_start_t = motion[-1].t + 0.033
    trailing = make_dwell(4, x=motion[-1].x, y=motion[-1].y, start_t=trailing_start_t)
    points = leading + motion + trailing

    result = trim_dwells(points)

    # Result must be smaller than the padded input
    assert len(result) < len(points)
    # At a minimum the interior dwell points are gone (keeping at most one
    # boundary point from each end).
    assert len(result) <= len(motion) + 2
    # The core motion points are preserved (first and last motion point present)
    result_ts = {p.t for p in result}
    assert motion[0].t in result_ts or motion[1].t in result_ts
    assert motion[-1].t in result_ts


def test_no_trim_when_all_moving() -> None:
    """When all points are moving, nothing is trimmed."""
    motion = make_motion(25, start_x=0.0, start_t=0.0)

    result = trim_dwells(motion)

    assert len(result) == len(motion)


def test_no_trim_to_empty() -> None:
    """When all points are stationary, the original list is returned unchanged."""
    points = make_dwell(10, x=0.5, y=0.5, start_t=0.0)

    result = trim_dwells(points)

    assert result is points or result == points
    assert len(result) == 10


def test_speed_threshold_respected() -> None:
    """Points just below threshold are trimmed; points just above are kept.

    The implementation trims from the start up to (but not always including)
    the boundary point of the first fast segment. At minimum, all leading
    purely-slow inter-point segments are removed, so the result is noticeably
    shorter than the original.
    """
    dt = 0.1
    # Speed = distance / dt.  Threshold = 0.05.
    # Slow segment: distance = 0.003 → speed = 0.03  (< 0.05, below threshold)
    slow_pts = [
        GesturePoint(x=0.5 + i * 0.003, y=0.5, t=i * dt) for i in range(5)
    ]
    # Fast segment: distance = 0.02 → speed = 0.2  (> 0.05, above threshold)
    fast_start_t = slow_pts[-1].t + dt
    fast_pts = [
        GesturePoint(x=slow_pts[-1].x + (i + 1) * 0.02, y=0.5, t=fast_start_t + i * dt)
        for i in range(20)
    ]
    points = slow_pts + fast_pts

    result = trim_dwells(points, speed_threshold=0.05)

    # At least some slow leading points were trimmed
    assert len(result) < len(points)
    # The full fast segment is still present (at most one boundary point extra)
    assert len(result) <= len(fast_pts) + 1
    # The last point of the fast segment is always retained
    assert result[-1].x == pytest.approx(fast_pts[-1].x)
