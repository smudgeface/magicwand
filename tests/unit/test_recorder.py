"""Unit tests for magicwand.recorder — Recorder and RecordingState."""

from __future__ import annotations

import pytest

from magicwand.recorder import Recorder, RecordingState
from magicwand.detection import DetectionResult

# Handy DetectionResult factory constants
_DETECTED = DetectionResult(detected=True, position=(320, 240), confidence=0.95, contour_area=100.0)
_NOT_DETECTED = DetectionResult(detected=False, position=None, confidence=0.0, contour_area=0.0)


def _make_recorder() -> Recorder:
    return Recorder(640, 480)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_is_idle() -> None:
    """A freshly created Recorder is in IDLE state."""
    recorder = _make_recorder()
    assert recorder.state == RecordingState.IDLE


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def test_start_recording_changes_state() -> None:
    """start_recording() transitions state to RECORDING."""
    recorder = _make_recorder()
    recorder.start_recording()
    assert recorder.state == RecordingState.RECORDING


# ---------------------------------------------------------------------------
# feed() behaviour
# ---------------------------------------------------------------------------

def test_feed_while_recording() -> None:
    """Feeding 10 detected results while recording accumulates 10 points."""
    recorder = _make_recorder()
    recorder.start_recording()
    for i in range(10):
        recorder.feed(_DETECTED, timestamp=float(i) * 0.05)
    assert recorder.point_count == 10


def test_feed_normalizes_coordinates() -> None:
    """A detection at the frame centre normalizes to (0.5, 0.5)."""
    recorder = _make_recorder()
    recorder.start_recording()
    recorder.feed(_DETECTED, timestamp=0.0)
    sample = recorder.current_sample
    assert sample is not None and len(sample) == 1
    pt = sample[0]
    assert abs(pt.x - 0.5) < 1e-9
    assert abs(pt.y - 0.5) < 1e-9


def test_feed_ignores_when_idle() -> None:
    """feed() while IDLE has no effect on point_count."""
    recorder = _make_recorder()
    recorder.feed(_DETECTED, timestamp=0.0)
    assert recorder.point_count == 0


# ---------------------------------------------------------------------------
# Auto-stop on tip lost
# ---------------------------------------------------------------------------

def test_auto_stop_on_tip_lost() -> None:
    """Recorder auto-transitions to REVIEW when tip is lost for > 0.5 s."""
    recorder = _make_recorder()
    recorder.start_recording()

    # Feed 10 detected results over 0–0.45 s
    for i in range(10):
        recorder.feed(_DETECTED, timestamp=i * 0.05)  # 0.0 … 0.45

    # Last detected was at 0.45 s. Feed non-detections for > 0.5 s beyond that.
    for i in range(7):
        t = 0.5 + i * 0.1  # 0.5, 0.6, 0.7, … 1.1
        recorder.feed(_NOT_DETECTED, timestamp=t)
        if recorder.state == RecordingState.REVIEW:
            break

    assert recorder.state == RecordingState.REVIEW


def test_auto_stop_only_after_some_detections() -> None:
    """Auto-stop does NOT trigger when no points have been captured yet."""
    recorder = _make_recorder()
    recorder.start_recording()

    # Immediately feed non-detected frames for a full second — no tip has ever
    # been seen, so the lost-timer must not activate.
    for i in range(11):
        recorder.feed(_NOT_DETECTED, timestamp=float(i) * 0.1)  # 0.0 … 1.0

    assert recorder.state == RecordingState.RECORDING


# ---------------------------------------------------------------------------
# Manual stop
# ---------------------------------------------------------------------------

def test_manual_stop_returns_sample() -> None:
    """stop_recording() returns the captured sample when >= 5 points exist."""
    recorder = _make_recorder()
    recorder.start_recording()
    for i in range(10):
        recorder.feed(_DETECTED, timestamp=float(i) * 0.05)
    sample = recorder.stop_recording()
    assert sample is not None
    assert len(sample) == 10


def test_stop_with_few_points_returns_none() -> None:
    """stop_recording() returns None and resets to IDLE when fewer than 5 points captured."""
    recorder = _make_recorder()
    recorder.start_recording()
    for i in range(3):
        recorder.feed(_DETECTED, timestamp=float(i) * 0.05)
    result = recorder.stop_recording()
    assert result is None
    assert recorder.state == RecordingState.IDLE


# ---------------------------------------------------------------------------
# Discard
# ---------------------------------------------------------------------------

def test_discard_returns_to_idle() -> None:
    """discard() resets state to IDLE and clears accumulated points."""
    recorder = _make_recorder()
    recorder.start_recording()
    for i in range(10):
        recorder.feed(_DETECTED, timestamp=float(i) * 0.05)
    recorder.discard()
    assert recorder.state == RecordingState.IDLE
    assert recorder.point_count == 0
