"""FastAPI application factory and uvicorn entry point."""

from __future__ import annotations

import asyncio
import logging
import queue
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from magicwand.actions import ActionDispatcher
from magicwand.camera import CameraThread, FrameBuffer, make_camera_source
from magicwand.captures import CaptureStore
from magicwand.homebridge import HomebridgeClient
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
    homebridge: HomebridgeClient,
    action_queue: queue.Queue,
    stop_event: asyncio.Event,
    event_bus: EventBus | None = None,
) -> None:
    """Background task that consumes the action queue and dispatches actions."""
    loop = asyncio.get_event_loop()
    while not stop_event.is_set():
        try:
            action_dict = await loop.run_in_executor(None, action_queue.get, True, 0.5)
            gesture_name = action_dict.get("gesture_name", "")

            if action_dict.get("type") == "homebridge":
                await _fire_homebridge_action(
                    homebridge, action_dict, gesture_name, event_bus
                )
            else:
                await _fire_http_action(
                    dispatcher, action_dict, gesture_name, event_bus
                )
        except queue.Empty:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Action worker error")


async def _fire_homebridge_action(
    client: HomebridgeClient,
    action_dict: dict,
    gesture_name: str,
    event_bus: EventBus | None,
) -> None:
    accessory_id = action_dict["accessory_id"]
    accessory_name = action_dict.get("accessory_name", accessory_id)
    action = action_dict.get("action", "toggle")
    t0 = __import__("time").monotonic()

    if action == "toggle":
        result = await client.toggle(accessory_id)
    elif action == "on":
        await client.set_characteristic(accessory_id, "On", 1)
        result = True
    elif action == "off":
        await client.set_characteristic(accessory_id, "On", 0)
        result = False
    else:
        result = None

    latency = (__import__("time").monotonic() - t0) * 1000
    success = result is not None

    if success:
        logger.info("Homebridge: %s → %s (%.0fms)", accessory_name, action, latency)
    else:
        logger.warning("Homebridge: %s → FAILED (%.0fms)", accessory_name, latency)

    if event_bus:
        if success:
            event_bus.emit(EventType.ACTION_FIRED, {
                "gesture_name": gesture_name,
                "accessory": accessory_name,
                "action": action,
                "result": result,
                "latency_ms": round(latency, 1),
            })
        else:
            event_bus.emit(EventType.ACTION_FAILED, {
                "gesture_name": gesture_name,
                "accessory": accessory_name,
                "action": action,
                "error": "homebridge request failed",
                "latency_ms": round(latency, 1),
            })


async def _fire_http_action(
    dispatcher: ActionDispatcher,
    action_dict: dict,
    gesture_name: str,
    event_bus: EventBus | None,
) -> None:
    from magicwand.actions import ActionConfig
    filtered = {k: v for k, v in action_dict.items() if k in ActionConfig.__dataclass_fields__}
    config = ActionConfig(**filtered)
    result = await dispatcher.fire(config)
    logger.info(
        "Action fired: %s → %s (%.0fms)",
        config.url,
        result.status_code or "error",
        result.latency_ms,
    )
    if event_bus:
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
    homebridge_client = HomebridgeClient(
        host=config.homebridge.host,
        port=config.homebridge.port,
        username=config.homebridge.username,
        password=config.homebridge.password,
    )
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
        app.state.homebridge = homebridge_client
        app.state.event_bus = event_bus
        await action_dispatcher.start()
        await homebridge_client.start()
        if homebridge_client.configured:
            await homebridge_client.connect()
        stop_event = asyncio.Event()
        worker_task = asyncio.create_task(
            _action_worker(action_dispatcher, homebridge_client, action_queue, stop_event, event_bus)
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
        await homebridge_client.stop()
        camera_thread.stop()
        camera_thread.join(timeout=5.0)
        event_bus.close()
        logger.info("magicwand stopped")

    app = FastAPI(title="magicwand", version="0.1.0", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(page_router)
    app.include_router(stream_router)
    app.include_router(ws_router)

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    return app


# Module-level app instance for `uvicorn magicwand.main:app`.
app = create_app()


def _check_port_available(host: str, port: int) -> None:
    """Exit with a clear error if the port is already in use by another process."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
    except OSError:
        print(
            f"\n[ERROR] Port {port} is already in use.\n"
            f"Kill the existing process: kill $(lsof -ti :{port})\n"
            f"Or find it: ps aux | grep magicwand\n",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        sock.close()


def run() -> None:
    """Console-script entry point: starts uvicorn with config-driven settings."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    cfg = get_config()
    _check_port_available(cfg.server.host, cfg.server.port)
    uvicorn.run(
        "magicwand.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
