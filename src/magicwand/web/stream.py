"""MJPEG streaming endpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_BOUNDARY = "frame"
_FRAME_TIMEOUT = 2.0  # seconds to wait for a new frame before giving up


async def _mjpeg_generator(request: Request) -> AsyncGenerator[bytes, None]:
    """Yield MJPEG multipart frames until the client disconnects."""
    frame_buffer = request.app.state.frame_buffer

    while True:
        # Check for client disconnect without blocking the event loop
        if await request.is_disconnected():
            logger.debug("MJPEG client disconnected")
            break

        # wait_for_frame is blocking — run it in a thread pool so we don't
        # block the asyncio event loop.
        frame: bytes | None = await asyncio.get_event_loop().run_in_executor(
            None, frame_buffer.wait_for_frame, _FRAME_TIMEOUT
        )

        if frame is None:
            # Timeout — camera may be slow; loop and check disconnect again
            continue

        yield (
            f"--{_BOUNDARY}\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame)}\r\n"
            "\r\n"
        ).encode()
        yield frame
        yield b"\r\n"


@router.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """Stream MJPEG frames to the client."""
    return StreamingResponse(
        _mjpeg_generator(request),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
    )
