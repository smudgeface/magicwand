from __future__ import annotations

from enum import Enum

from magicwand.detection import DetectionResult
from magicwand.gestures import GesturePoint, GestureSample


class RecordingState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    REVIEW = "review"


class Recorder:
    """State machine that captures wand tip positions into a GestureSample.

    Feed detection results each frame. The recorder normalizes pixel
    coordinates to [0, 1] and auto-stops when the tip is lost for more
    than 0.5 seconds.
    """

    def __init__(self, frame_width: int, frame_height: int) -> None:
        self._width = frame_width
        self._height = frame_height
        self._state = RecordingState.IDLE
        self._points: list[GesturePoint] = []
        self._start_time: float = 0.0
        self._tip_lost_time: float | None = None
        self._tip_lost_timeout = 0.5  # seconds
        self._has_seen_tip: bool = False

    @property
    def state(self) -> RecordingState:
        """Current recording state."""
        return self._state

    @property
    def current_sample(self) -> GestureSample | None:
        """The sample being recorded, or None if IDLE."""
        if self._state == RecordingState.IDLE:
            return None
        return list(self._points)

    @property
    def point_count(self) -> int:
        """Number of points captured so far."""
        return len(self._points)

    def start_recording(self) -> None:
        """Transition to RECORDING state. Clears any previous data."""
        self._state = RecordingState.RECORDING
        self._points = []
        self._start_time = 0.0
        self._tip_lost_time = None
        self._has_seen_tip = False

    def feed(self, detection: DetectionResult, timestamp: float) -> None:
        """Feed a detection result into the recorder.

        When recording:
        - If detected: normalize coords and append to points.
        - If not detected and we have previously seen the tip: track how
          long the tip has been lost.
        - If tip lost for > timeout: auto-transition to REVIEW.
        """
        if self._state != RecordingState.RECORDING:
            return

        if detection.detected and detection.position is not None:
            # First detection sets the start time
            if not self._has_seen_tip:
                self._has_seen_tip = True
                self._start_time = timestamp

            self._tip_lost_time = None
            nx, ny = self._normalize(detection.position[0], detection.position[1])
            relative_t = timestamp - self._start_time
            self._points.append(GesturePoint(x=nx, y=ny, t=relative_t))
        else:
            # Tip not detected — only start the lost timer if we've already
            # seen at least one detection and have captured points.
            if self._has_seen_tip and len(self._points) > 0:
                if self._tip_lost_time is None:
                    self._tip_lost_time = timestamp
                elif (timestamp - self._tip_lost_time) > self._tip_lost_timeout:
                    # Auto-stop: transition to REVIEW
                    self._state = RecordingState.REVIEW
                    self._tip_lost_time = None

    def stop_recording(self) -> GestureSample | None:
        """Manually stop recording. Returns the sample or None if too few points.

        Can be called from RECORDING or REVIEW state. If fewer than 5 points
        were captured, returns None and transitions to IDLE.
        """
        if self._state == RecordingState.IDLE:
            return None

        if len(self._points) < 5:
            self._state = RecordingState.IDLE
            self._points = []
            return None

        self._state = RecordingState.REVIEW
        return list(self._points)

    def discard(self) -> None:
        """Discard the current sample and return to IDLE."""
        self._state = RecordingState.IDLE
        self._points = []
        self._tip_lost_time = None
        self._has_seen_tip = False

    def _normalize(self, x: int, y: int) -> tuple[float, float]:
        """Normalize pixel coordinates to [0, 1] range, clamped."""
        nx = max(0.0, min(1.0, x / self._width))
        ny = max(0.0, min(1.0, y / self._height))
        return nx, ny
