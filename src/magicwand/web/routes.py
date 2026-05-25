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
