"""Unit tests for magicwand.camera."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from magicwand.camera import (
    CameraThread,
    FrameBuffer,
    MockCamera,
    make_camera_source,
)
from magicwand.config import CameraConfig, MockCameraConfig


def _default_camera_config(**overrides) -> CameraConfig:
    """Return a CameraConfig suitable for unit testing."""
    kwargs = dict(
        width=640,
        height=480,
        fps=30,
        source="mock",
        mock=MockCameraConfig(dot_speed=2.0),
    )
    kwargs.update(overrides)
    return CameraConfig(**kwargs)


class TestMockCamera:
    def test_mock_camera_frame_shape(self) -> None:
        """get_frame() returns an ndarray with shape (480, 640, 3)."""
        cfg = _default_camera_config()
        cam = MockCamera(cfg)
        cam.start()
        frame = cam.get_frame()

        assert isinstance(frame, np.ndarray)
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

    def test_mock_camera_frame_has_bright_dot(self) -> None:
        """The generated frame contains at least some pure-white pixels."""
        cfg = _default_camera_config()
        cam = MockCamera(cfg)
        cam.start()
        frame = cam.get_frame()

        # A white pixel has all three channels at 255
        white_pixels = np.all(frame == 255, axis=2)
        assert white_pixels.sum() > 0, "Expected at least one white pixel in the frame"

    def test_mock_camera_stop_is_safe(self) -> None:
        """stop() can be called without error even when never started properly."""
        cfg = _default_camera_config()
        cam = MockCamera(cfg)
        cam.stop()  # must not raise


class TestFrameBuffer:
    def test_frame_buffer_put_get(self) -> None:
        """Bytes put into the buffer can be retrieved with get()."""
        buf = FrameBuffer()
        data = b"\xff\xd8\xff" + b"\x00" * 100  # fake JPEG header + padding

        buf.put(data)

        assert buf.get() == data

    def test_frame_buffer_initial_get_is_empty(self) -> None:
        """Before any put(), get() returns empty bytes."""
        buf = FrameBuffer()
        assert buf.get() == b""

    def test_frame_buffer_wait_returns_on_put(self) -> None:
        """wait_for_frame() wakes up and returns data placed by another thread."""
        buf = FrameBuffer()
        payload = b"hello-frame"

        def _delayed_put():
            time.sleep(0.1)
            buf.put(payload)

        t = threading.Thread(target=_delayed_put, daemon=True)
        t.start()

        result = buf.wait_for_frame(timeout=2.0)
        t.join(timeout=1.0)

        assert result == payload

    def test_frame_buffer_wait_timeout(self) -> None:
        """wait_for_frame() returns None when no frame arrives within the timeout."""
        buf = FrameBuffer()

        result = buf.wait_for_frame(timeout=0.05)

        assert result is None

    def test_frame_buffer_multiple_puts(self) -> None:
        """Successive put() calls overwrite the stored frame."""
        buf = FrameBuffer()
        buf.put(b"frame-one")
        buf.put(b"frame-two")

        assert buf.get() == b"frame-two"


class TestCameraThread:
    def test_camera_thread_produces_frames(self) -> None:
        """CameraThread feeds FrameBuffer with JPEG data within 1 second."""
        cfg = _default_camera_config(fps=30)
        source = make_camera_source(cfg)
        buf = FrameBuffer()
        thread = CameraThread(source, buf, cfg.fps)

        try:
            thread.start()
            # Wait up to 1 second for a frame to appear
            frame = buf.wait_for_frame(timeout=1.0)
        finally:
            thread.stop()
            thread.join(timeout=2.0)

        assert frame is not None, "Expected a frame within 1 second"
        # Frames are JPEG-encoded: they must start with FF D8 FF
        assert frame[:3] == b"\xff\xd8\xff", "Frame should start with JPEG magic bytes"

    def test_camera_thread_stops_cleanly(self) -> None:
        """CameraThread exits its loop after stop() is called."""
        cfg = _default_camera_config()
        source = make_camera_source(cfg)
        buf = FrameBuffer()
        thread = CameraThread(source, buf, cfg.fps)

        thread.start()
        # Give it a moment to produce at least one frame
        buf.wait_for_frame(timeout=1.0)
        thread.stop()
        thread.join(timeout=2.0)

        assert not thread.is_alive(), "CameraThread should have stopped"
