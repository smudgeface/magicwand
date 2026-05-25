"""FastAPI application factory and uvicorn entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from magicwand.camera import CameraThread, FrameBuffer, make_camera_source
from magicwand.config import Config, clear_config_cache, get_config
from magicwand.web.routes import router as page_router
from magicwand.web.stream import router as stream_router

logger = logging.getLogger(__name__)

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

    # Build camera objects early so lifespan can close over them.
    camera_source = make_camera_source(config.camera)
    frame_buffer = FrameBuffer()
    camera_thread = CameraThread(camera_source, frame_buffer, config.camera.fps)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup
        app.state.frame_buffer = frame_buffer
        app.state.camera_thread = camera_thread
        camera_thread.start()
        logger.info(
            "magicwand started — camera source=%s, server=%s:%d",
            config.camera.source,
            config.server.host,
            config.server.port,
        )
        yield
        # Shutdown
        camera_thread.stop()
        camera_thread.join(timeout=5.0)
        logger.info("magicwand stopped")

    app = FastAPI(title="magicwand", version="0.1.0", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    app.include_router(page_router)
    app.include_router(stream_router)

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
