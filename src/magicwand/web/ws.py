"""WebSocket endpoint for live event streaming."""
from __future__ import annotations

import asyncio
import queue
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    await websocket.accept()
    event_bus = websocket.app.state.event_bus
    q = event_bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, q.get, True, 1.0
                )
                await websocket.send_json(event)
            except queue.Empty:
                continue
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        event_bus.unsubscribe(q)
