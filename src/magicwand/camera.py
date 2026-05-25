"""Camera capture, frame buffering, and the background camera thread."""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from typing import Protocol

import cv2
import numpy as np

from magicwand.config import CameraConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class CameraSource(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_frame(self) -> np.ndarray: ...  # BGR, HxWx3


# ---------------------------------------------------------------------------
# MockCamera
# ---------------------------------------------------------------------------

class MockCamera:
    """Generates synthetic 640x480 frames with a white dot moving in a figure-8."""

    def __init__(self, config: CameraConfig) -> None:
        self._width = config.width
        self._height = config.height
        self._fps = config.fps
        # figure-8 animation speed (radians per second)
        self._angular_speed = config.mock.dot_speed * 0.5

    def start(self) -> None:
        pass  # nothing to initialise

    def stop(self) -> None:
        pass

    def get_frame(self) -> np.ndarray:
        """Return one BGR frame with the dot position computed from wall time."""
        t = time.monotonic()
        angle = t * self._angular_speed

        # Lissajous figure-8: x=sin(t), y=sin(2t)/2
        cx = self._width // 2
        cy = self._height // 2
        rx = int(self._width * 0.35)
        ry = int(self._height * 0.35)

        dot_x = int(cx + rx * math.sin(angle))
        dot_y = int(cy + ry * math.sin(2 * angle) / 2)

        # Low-level random noise (0-15) to simulate a real IR camera's noise floor
        noise = np.random.randint(0, 16, (self._height, self._width, 3), dtype=np.uint8)
        frame = noise.copy()
        cv2.circle(frame, (dot_x, dot_y), 10, (255, 255, 255), -1)
        return frame


# ---------------------------------------------------------------------------
# PiCameraSource (stub)
# ---------------------------------------------------------------------------

class PiCameraSource:
    """Wraps picamera2 — to be implemented when hardware arrives."""

    def __init__(self, config: CameraConfig) -> None:  # noqa: ARG002
        pass

    def start(self) -> None:
        raise NotImplementedError(
            "PiCameraSource is not yet implemented. "
            "Set camera.source = 'mock' in config.toml for development."
        )

    def stop(self) -> None:
        raise NotImplementedError("PiCameraSource is not yet implemented.")

    def get_frame(self) -> np.ndarray:
        raise NotImplementedError("PiCameraSource is not yet implemented.")


# ---------------------------------------------------------------------------
# FrameBuffer
# ---------------------------------------------------------------------------

class FrameBuffer:
    """Thread-safe holder for the latest JPEG-encoded frame.

    The camera thread writes frames; one or many streaming consumers read them.
    Consumers can block until a new frame is available via wait_for_frame().

    Implementation note: each put() replaces the shared Event with a new one
    so that consumers who call wait_for_frame() *after* a put() still receive
    the next notification correctly (avoids the set-then-clear race).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: bytes = b""
        # _ready is replaced on every put; existing waiters hold a reference
        # to the old event and will be woken by its set().
        self._ready = threading.Event()

    def put(self, frame: bytes) -> None:
        """Store a new JPEG frame and notify all current waiters."""
        with self._lock:
            self._frame = frame
            # Wake all consumers waiting on the old event, then hand them a
            # fresh event for the *next* frame so we don't double-deliver.
            old_ready = self._ready
            self._ready = threading.Event()
        old_ready.set()

    def get(self) -> bytes:
        """Return the current frame (may be empty bytes if none yet)."""
        with self._lock:
            return self._frame

    def wait_for_frame(self, timeout: float = 1.0) -> bytes | None:
        """Block until a new frame arrives, then return it.

        Returns:
            The JPEG bytes of the new frame, or None if timeout expired.
        """
        with self._lock:
            event = self._ready
        got_new = event.wait(timeout=timeout)
        if not got_new:
            return None
        with self._lock:
            return self._frame


# ---------------------------------------------------------------------------
# CameraThread
# ---------------------------------------------------------------------------

class CameraThread(threading.Thread):
    """Daemon thread that continuously captures frames and feeds FrameBuffer."""

    _JPEG_QUALITY = 80
    _LOG_FPS_INTERVAL = 5.0  # seconds between FPS log messages

    def __init__(
        self,
        source: CameraSource,
        buffer: FrameBuffer,
        fps: int,
        detector=None,
        recorder=None,
        watcher=None,
        frame_width: int = 640,
        frame_height: int = 480,
        gesture_store=None,
        action_queue: queue.Queue | None = None,
        event_bus=None,
    ) -> None:
        super().__init__(name="camera-thread", daemon=True)
        self._source = source
        self._buffer = buffer
        self._fps = fps
        self._detector = detector
        self._recorder = recorder
        self._watcher = watcher
        self._source_width = frame_width
        self._source_height = frame_height
        self._gesture_store = gesture_store
        self._action_queue = action_queue
        self._event_bus = event_bus
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self._stop_event.set()

    def run(self) -> None:
        self._source.start()
        logger.info("CameraThread started (target %d fps)", self._fps)

        frame_interval = 1.0 / self._fps
        frame_count = 0
        fps_timer = time.monotonic()

        try:
            while not self._stop_event.is_set():
                t0 = time.monotonic()

                raw = self._source.get_frame()

                if self._detector is not None:
                    raw, result = self._detector.process(raw)
                    ts = time.monotonic()
                    if self._recorder is not None:
                        self._recorder.feed(result, ts)
                    if self._watcher is not None:
                        from magicwand.recorder import RecordingState
                        if self._recorder is None or self._recorder.state == RecordingState.IDLE:
                            match_result = self._watcher.feed(result, ts, self._source_width, self._source_height)
                            if match_result and match_result.matched:
                                if self._gesture_store and self._action_queue is not None:
                                    gesture = self._gesture_store.get(match_result.gesture_name)
                                    if gesture and gesture.action:
                                        self._action_queue.put(gesture.action)
                            if self._event_bus and match_result:
                                from magicwand.events import EventType
                                if match_result.matched:
                                    self._event_bus.emit(EventType.GESTURE_RECOGNIZED, {
                                        "gesture_name": match_result.gesture_name,
                                        "confidence": round(match_result.confidence, 3),
                                        "distance": round(match_result.distance, 4),
                                    })
                                else:
                                    self._event_bus.emit(EventType.GESTURE_REJECTED, {
                                        "reason": "no_match",
                                    })

                ok, buf = cv2.imencode(
                    ".jpg", raw, [cv2.IMWRITE_JPEG_QUALITY, self._JPEG_QUALITY]
                )
                if ok:
                    self._buffer.put(buf.tobytes())
                    frame_count += 1

                # Log actual FPS every few seconds
                elapsed_fps = time.monotonic() - fps_timer
                if elapsed_fps >= self._LOG_FPS_INTERVAL:
                    actual_fps = frame_count / elapsed_fps
                    logger.debug("CameraThread: %.1f fps", actual_fps)
                    frame_count = 0
                    fps_timer = time.monotonic()

                # Sleep only the remaining time in the frame budget
                elapsed = time.monotonic() - t0
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except Exception:
            logger.exception("CameraThread crashed")
        finally:
            self._source.stop()
            logger.info("CameraThread stopped")


# ---------------------------------------------------------------------------
# WebcamCamera
# ---------------------------------------------------------------------------

class WebcamCamera:
    """OpenCV VideoCapture source for USB/UVC webcams (Mac development)."""

    def __init__(self, config: CameraConfig) -> None:
        self._width = config.width
        self._height = config.height
        self._device_index = config.webcam_device
        self._exposure = config.webcam_exposure
        self._cap: cv2.VideoCapture | None = None

    def start(self) -> None:
        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open webcam device {self._device_index}. "
                "Check that a camera is connected."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        if self._exposure is not None:
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # manual mode
            self._cap.set(cv2.CAP_PROP_EXPOSURE, self._exposure)
            logger.info("Webcam exposure set to %s", self._exposure)
        else:
            logger.info("Webcam using auto exposure")

    def stop(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None

    def get_frame(self) -> np.ndarray:
        if self._cap is None:
            raise RuntimeError("WebcamCamera not started")
        ret, frame = self._cap.read()
        if not ret or frame is None:
            return np.zeros((self._height, self._width, 3), dtype=np.uint8)
        return frame


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_camera_source(config: CameraConfig) -> CameraSource:
    """Instantiate the right CameraSource based on config.

    When source is "auto": try webcam first (works on Mac), then picamera2
    (works on Pi), then fall back to mock.
    """
    if config.source == "mock":
        return MockCamera(config)
    if config.source == "webcam":
        return WebcamCamera(config)
    if config.source == "picamera2":
        return PiCameraSource(config)
    if config.source == "auto":
        # Try webcam (Mac/USB cameras)
        try:
            cap = cv2.VideoCapture(config.webcam_device)
            if cap.isOpened():
                cap.release()
                logger.info("Auto-detected webcam at device %d", config.webcam_device)
                return WebcamCamera(config)
            cap.release()
        except Exception:
            pass
        # Try picamera2 (Pi) — probe for an actual connected camera
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cam.close()
            logger.info("Auto-detected picamera2 with connected camera")
            return PiCameraSource(config)
        except Exception:
            pass
        # Fall back to mock
        logger.info("No camera detected, falling back to mock")
        return MockCamera(config)
    raise ValueError(f"Unknown camera source: {config.source!r}")
