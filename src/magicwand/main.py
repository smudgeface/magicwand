"""FastAPI application factory and uvicorn entry point."""

from __future__ import annotations

import asyncio
import logging
import queue
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from magicwand.actions import ActionDispatcher
from magicwand.camera import CameraThread, FrameBuffer, make_camera_source
from magicwand.captures import CaptureStore
from magicwand.config import Config, clear_config_cache, get_config
from magicwand.detection import Detector
from magicwand.events import EventBus, EventType
from magicwand.gestures import GestureStore
from magicwand.matching import GestureWatcher
from magicwand.recorder import Recorder
from magicwand.web.routes import router as page_router
from magicwand.web.stream import router as stream_router
from magicwand.web.ws import router as ws_router

logger = logging.getLogger(__name__)


async def _action_worker(
    dispatcher: ActionDispatcher,
    action_queue: queue.Queue,
    stop_event: asyncio.Event,
    event_bus: EventBus | None = None,
) -> None:
    """Background task that consumes the action queue and dispatches HTTP requests."""
    loop = asyncio.get_event_loop()
    while not stop_event.is_set():
        try:
            action_dict = await loop.run_in_executor(None, action_queue.get, True, 0.5)
            from magicwand.actions import ActionConfig
            config = ActionConfig(**action_dict)
            result = await dispatcher.fire(config)
            logger.info(
                "Action fired: %s → %s (%.0fms)",
                config.url,
                result.status_code or "error",
                result.latency_ms,
            )
            if event_bus is not None:
                gesture_name = action_dict.get("gesture_name", "")
                if result.success:
                    event_bus.emit(EventType.ACTION_FIRED, {
                        "gesture_name": gesture_name,
                        "url": config.url,
                        "status_code": result.status_code,
                        "latency_ms": round(result.latency_ms, 1),
                    })
                else:
                    event_bus.emit(EventType.ACTION_FAILED, {
                        "gesture_name": gesture_name,
                        "url": config.url,
                        "error": result.error or "unknown",
                        "latency_ms": round(result.latency_ms, 1),
                    })
        except queue.Empty:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Action worker error")

_STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app(config_path: Path | str | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config_path: Optional path to config.toml. When provided the config
                     cache is cleared and re-read from this path — useful for
                     tests that supply a temporary config file.
    """
    if config_path is not None:
        clear_config_cache()

    config: Config = get_config(config_path)

    # Resolve directories relative to config file location or CWD.
    if config_path is not None:
        base_dir = Path(config_path).parent
    else:
        base_dir = Path.cwd()
    gestures_dir = base_dir / config.gestures.directory
    log_dir = base_dir / config.logging.directory
    captures_dir = base_dir / config.captures.directory
    gestures_dir.mkdir(parents=True, exist_ok=True)
    captures_dir.mkdir(parents=True, exist_ok=True)

    # Build camera objects early so lifespan can close over them.
    camera_source = make_camera_source(config.camera)
    frame_buffer = FrameBuffer()
    detector = Detector(config.detection)
    gesture_store = GestureStore(gestures_dir)
    capture_store = CaptureStore(captures_dir, config.captures.max_captures)
    recorder = Recorder(config.camera.width, config.camera.height)
    watcher = GestureWatcher(gesture_store, config.matching, capture_store=capture_store)
    gesture_store.on_change = watcher.invalidate_cache
    action_queue: queue.Queue = queue.Queue()
    action_dispatcher = ActionDispatcher()
    event_bus = EventBus(
        log_dir=log_dir,
        max_file_size=config.logging.max_file_size,
        max_files=config.logging.max_files,
    )
    camera_thread = CameraThread(
        camera_source,
        frame_buffer,
        config.camera.fps,
        detector,
        recorder,
        watcher=watcher,
        frame_width=config.camera.width,
        frame_height=config.camera.height,
        gesture_store=gesture_store,
        action_queue=action_queue,
        event_bus=event_bus,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup
        app.state.frame_buffer = frame_buffer
        app.state.camera_thread = camera_thread
        app.state.detector = detector
        app.state.gesture_store = gesture_store
        app.state.capture_store = capture_store
        app.state.recorder = recorder
        app.state.watcher = watcher
        app.state.action_dispatcher = action_dispatcher
        app.state.event_bus = event_bus
        await action_dispatcher.start()
        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(
            _action_worker(action_dispatcher, action_queue, stop_event, event_bus)
        )
        camera_thread.start()
        logger.info(
            "magicwand started — camera source=%s, server=%s:%d",
            config.camera.source,
            config.server.host,
            config.server.port,
        )
        event_bus.emit(EventType.SYSTEM_START, {
            "camera_source": config.camera.source,
            "server_port": config.server.port,
        })
        yield
        # Shutdown
        stop_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await action_dispatcher.stop()
        camera_thread.stop()
        camera_thread.join(timeout=5.0)
        event_bus.close()
        logger.info("magicwand stopped")

    app = FastAPI(title="magicwand", version="0.1.0", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(page_router)
    app.include_router(stream_router)
    app.include_router(ws_router)

    return app


# Module-level app instance for `uvicorn magicwand.main:app`.
app = create_app()


def run() -> None:
    """Console-script entry point: starts uvicorn with config-driven settings."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    cfg = get_config()
    uvicorn.run(
        "magicwand.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
