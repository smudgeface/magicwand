"""Page routes: HTML views and the health check endpoint."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

_start_time = time.monotonic()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main page with the live camera feed."""
    return templates.TemplateResponse(request, "index.html")


@router.get("/api/health")
async def health() -> dict:
    """Return service status and uptime in seconds."""
    return {"status": "ok", "uptime": round(time.monotonic() - _start_time, 1)}


@router.put("/api/settings/detection")
async def update_detection_settings(request: Request) -> dict:
    """Update detection parameters at runtime."""
    body = await request.json()
    detector = request.app.state.detector
    detector.update_config(**body)
    cfg = detector._config
    return {
        "threshold": cfg.threshold,
        "min_area": cfg.min_area,
        "max_area": cfg.max_area,
        "blur_kernel": cfg.blur_kernel,
        "trail_length": cfg.trail_length,
    }


@router.get("/api/detection/status")
async def detection_status(request: Request) -> dict:
    """Return current detection state."""
    detector = request.app.state.detector
    return {
        "fps": round(detector.fps, 1),
        "trail_length": len(detector.trail),
        "config": {
            "threshold": detector._config.threshold,
            "min_area": detector._config.min_area,
            "max_area": detector._config.max_area,
            "blur_kernel": detector._config.blur_kernel,
            "trail_length": detector._config.trail_length,
        },
    }
