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


# ---------------------------------------------------------------------------
# Gesture endpoints
# ---------------------------------------------------------------------------

@router.get("/api/gestures")
async def list_gestures(request: Request) -> list[dict]:
    """Return all gestures with summary info."""
    store = request.app.state.gesture_store
    gestures = []
    for name in store.list():
        g = store.get(name)
        gestures.append({
            "name": g.name,
            "sample_count": len(g.samples),
            "has_action": g.action is not None,
            "created_at": g.created_at,
        })
    return gestures


@router.post("/api/gestures", status_code=201)
async def create_gesture(request: Request) -> dict:
    """Create a new empty gesture."""
    body = await request.json()
    store = request.app.state.gesture_store
    name = body.get("name", "")
    try:
        gesture = store.create(name)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"name": gesture.name, "created_at": gesture.created_at}


@router.get("/api/gestures/{name}")
async def get_gesture(request: Request, name: str) -> dict:
    """Return full gesture detail including all samples."""
    store = request.app.state.gesture_store
    g = store.get(name)
    if g is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "name": g.name,
        "created_at": g.created_at,
        "sample_count": len(g.samples),
        "samples": [[{"x": p.x, "y": p.y, "t": p.t} for p in s] for s in g.samples],
        "action": g.action,
    }


@router.delete("/api/gestures/{name}")
async def delete_gesture(request: Request, name: str) -> dict:
    """Delete a gesture by name."""
    store = request.app.state.gesture_store
    if not store.delete(name):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"deleted": name}


@router.post("/api/gestures/{name}/samples", status_code=201)
async def add_sample(request: Request, name: str) -> dict:
    """Add a recorded sample to an existing gesture."""
    store = request.app.state.gesture_store
    body = await request.json()
    from magicwand.gestures import GesturePoint
    sample = [GesturePoint(x=p["x"], y=p["y"], t=p["t"]) for p in body]
    try:
        count = store.add_sample(name, sample)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=404)
    return {"sample_count": count}


@router.delete("/api/gestures/{name}/samples/{index}")
async def remove_sample(request: Request, name: str, index: int) -> dict:
    """Remove a sample from a gesture by index."""
    store = request.app.state.gesture_store
    if not store.remove_sample(name, index):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "sample not found"}, status_code=404)
    return {"removed": index}


# ---------------------------------------------------------------------------
# Recording endpoints
# ---------------------------------------------------------------------------

@router.get("/api/recording/status")
async def recording_status(request: Request) -> dict:
    """Return the current recorder state and point count."""
    recorder = request.app.state.recorder
    return {
        "state": recorder.state.value,
        "point_count": recorder.point_count,
    }


@router.post("/api/recording/start")
async def start_recording(request: Request) -> dict:
    """Begin recording a new gesture sample."""
    recorder = request.app.state.recorder
    recorder.start_recording()
    return {"state": recorder.state.value}


@router.post("/api/recording/stop")
async def stop_recording(request: Request) -> dict:
    """Stop recording and return the captured sample (or None if too few points)."""
    recorder = request.app.state.recorder
    sample = recorder.stop_recording()
    if sample is None:
        return {"state": recorder.state.value, "sample": None, "reason": "too few points"}
    return {
        "state": recorder.state.value,
        "sample": [{"x": p.x, "y": p.y, "t": p.t} for p in sample],
        "point_count": len(sample),
    }
