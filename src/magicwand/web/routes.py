"""Page routes: HTML views and the health check endpoint."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"name": gesture.name, "created_at": gesture.created_at}


@router.get("/api/gestures/{name}")
async def get_gesture(request: Request, name: str) -> dict:
    """Return full gesture detail including all samples."""
    store = request.app.state.gesture_store
    g = store.get(name)
    if g is None:
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
        return JSONResponse({"error": str(e)}, status_code=404)
    return {"sample_count": count}


@router.delete("/api/gestures/{name}/samples/{index}")
async def remove_sample(request: Request, name: str, index: int) -> dict:
    """Remove a sample from a gesture by index."""
    store = request.app.state.gesture_store
    if not store.remove_sample(name, index):
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


# ---------------------------------------------------------------------------
# Matching endpoints
# ---------------------------------------------------------------------------

@router.get("/api/matching/status")
async def matching_status(request: Request) -> dict:
    """Return the current gesture watcher state and most recent match result."""
    watcher = request.app.state.watcher
    last = watcher.last_match
    return {
        "state": watcher.state.value,
        "last_match": {
            "matched": last.matched,
            "gesture_name": last.gesture_name,
            "confidence": round(last.confidence, 3),
            "distance": round(last.distance, 4),
        } if last else None,
    }


@router.put("/api/settings/matching")
async def update_matching_settings(request: Request) -> dict:
    """Update gesture matching parameters at runtime."""
    body = await request.json()
    watcher = request.app.state.watcher
    cfg = watcher._config
    for key, value in body.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return {
        "distance_threshold": cfg.distance_threshold,
        "min_confidence": cfg.min_confidence,
        "gap_timeout": cfg.gap_timeout,
        "cooldown_time": cfg.cooldown_time,
        "min_gesture_points": cfg.min_gesture_points,
        "resample_count": cfg.resample_count,
    }


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------

@router.put("/api/gestures/{name}/action")
async def set_action(request: Request, name: str) -> dict:
    """Set or update the action for a gesture."""
    body = await request.json()
    store = request.app.state.gesture_store
    if not store.set_action(name, body):
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    return {"name": name, "action": body}


@router.delete("/api/gestures/{name}/action")
async def clear_action(request: Request, name: str) -> dict:
    """Clear the action for a gesture."""
    store = request.app.state.gesture_store
    if not store.set_action(name, None):
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    return {"name": name, "action": None}


@router.post("/api/gestures/{name}/action/test")
async def test_action(request: Request, name: str) -> dict:
    """Fire the gesture's action immediately (for testing)."""
    store = request.app.state.gesture_store
    g = store.get(name)
    if g is None:
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    if g.action is None:
        return JSONResponse({"error": "no action configured"}, status_code=400)
    from magicwand.actions import ActionConfig
    dispatcher = request.app.state.action_dispatcher
    config = ActionConfig(**g.action)
    result = await dispatcher.fire(config)
    return {
        "success": result.success,
        "status_code": result.status_code,
        "latency_ms": round(result.latency_ms, 1),
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Homebridge endpoints
# ---------------------------------------------------------------------------

@router.get("/api/homebridge/presets")
async def homebridge_presets(request: Request) -> list[dict]:
    """Return available Homebridge presets with host/port filled in."""
    from magicwand.config import get_config
    cfg = get_config()
    hb = cfg.homebridge
    result = []
    for p in hb.presets:
        result.append({
            "name": p.name,
            "method": p.method,
            "url_template": p.url_template.format(
                host=hb.host, port=hb.port, accessory_id="{accessory_id}"
            ),
        })
    return result
