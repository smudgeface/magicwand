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


@router.get("/gestures", response_class=HTMLResponse)
async def gestures_page(request: Request) -> HTMLResponse:
    """Render the gesture list page."""
    return templates.TemplateResponse(request, "gestures.html")


@router.get("/train", response_class=HTMLResponse)
async def train_page(request: Request) -> HTMLResponse:
    """Render the gesture training wizard page."""
    return templates.TemplateResponse(request, "train.html")


@router.get("/gesture/{name}", response_class=HTMLResponse)
async def gesture_detail_page(request: Request, name: str) -> HTMLResponse:
    """Render the gesture detail/edit page."""
    return templates.TemplateResponse(request, "gesture-detail.html", {"name": name})


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    """Render the admin page."""
    return templates.TemplateResponse(request, "settings.html")


@router.get("/api/health")
async def health() -> dict:
    """Return service status and uptime in seconds."""
    return {"status": "ok", "uptime": round(time.monotonic() - _start_time, 1)}


@router.get("/api/system/info")
async def system_info(request: Request) -> dict:
    """Return system stats: uptime, CPU temp, RAM, disk, camera, FPS, versions."""
    import platform
    import magicwand

    # Uptime
    uptime = round(time.monotonic() - _start_time, 1)

    # CPU temp — Linux: /sys/class/thermal, macOS: not available without extras
    cpu_temp = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp = round(int(f.read().strip()) / 1000, 1)
    except (FileNotFoundError, ValueError):
        pass

    # RAM — Linux: /proc/meminfo, macOS: sysctl + vm_stat
    import subprocess
    ram_used = None
    ram_total = None
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
            ram_total = round(meminfo.get("MemTotal", 0) / 1024, 0)
            available = meminfo.get("MemAvailable", 0)
            ram_used = round((meminfo.get("MemTotal", 0) - available) / 1024, 0)
    except FileNotFoundError:
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            ram_total = round(int(out.strip()) / (1024 * 1024))
            vm = subprocess.check_output(["vm_stat"], text=True)
            pages = {}
            for line in vm.strip().splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    v = v.strip().rstrip(".")
                    if v.isdigit():
                        pages[k.strip()] = int(v)
            page_size = 16384
            free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
            inactive = pages.get("Pages inactive", 0)
            ram_free = round((free_pages + inactive) * page_size / (1024 * 1024))
            ram_used = ram_total - ram_free
        except (subprocess.SubprocessError, ValueError, OSError):
            pass

    # Disk
    import shutil
    disk = shutil.disk_usage("/")

    # Detection FPS
    detector = getattr(request.app.state, "detector", None)
    fps = round(detector.fps, 1) if detector else 0

    # Camera source
    from magicwand.config import get_config
    cfg = get_config()

    return {
        "uptime_seconds": uptime,
        "cpu_temp_c": cpu_temp,
        "ram_used_mb": ram_used,
        "ram_total_mb": ram_total,
        "disk_used_gb": round(disk.used / (1024**3), 1),
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "camera_source": cfg.camera.source,
        "detection_fps": fps,
        "python_version": platform.python_version(),
        "app_version": magicwand.__version__,
    }


@router.put("/api/settings/detection")
async def update_detection_settings(request: Request) -> dict:
    """Update detection parameters at runtime and persist to config.toml."""
    from magicwand.config import get_config, save_config
    body = await request.json()
    detector = request.app.state.detector
    detector.update_config(**body)
    cfg = detector._config
    app_cfg = get_config()
    app_cfg.detection.threshold = cfg.threshold
    app_cfg.detection.min_area = cfg.min_area
    app_cfg.detection.max_area = cfg.max_area
    app_cfg.detection.blur_kernel = cfg.blur_kernel
    app_cfg.detection.trail_length = cfg.trail_length
    save_config()
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
    """Update gesture matching parameters at runtime and persist to config.toml."""
    from magicwand.config import get_config, save_config
    body = await request.json()
    watcher = request.app.state.watcher
    cfg = watcher._config
    for key, value in body.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    app_cfg = get_config()
    for key in vars(app_cfg.matching):
        setattr(app_cfg.matching, key, getattr(cfg, key))
    save_config()
    return {
        "distance_threshold": cfg.distance_threshold,
        "min_confidence": cfg.min_confidence,
        "gap_timeout": cfg.gap_timeout,
        "cooldown_time": cfg.cooldown_time,
        "min_gesture_points": cfg.min_gesture_points,
        "resample_count": cfg.resample_count,
        "dwell_speed_threshold": cfg.dwell_speed_threshold,
        "dwell_min_points": cfg.dwell_min_points,
        "linearity_threshold": cfg.linearity_threshold,
        "min_curvature": cfg.min_curvature,
        "min_segment_duration": cfg.min_segment_duration,
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

@router.get("/api/logs")
async def get_logs(request: Request, since: str = None, type: str = None, limit: int = 100) -> list[dict]:
    """Return historical log entries, optionally filtered by timestamp and event type."""
    event_bus = request.app.state.event_bus
    return event_bus.read_logs(since=since, event_type=type, limit=limit)


@router.get("/captures", response_class=HTMLResponse)
async def captures_page(request: Request) -> HTMLResponse:
    """Render the capture history page."""
    return templates.TemplateResponse(request, "captures.html")


# ---------------------------------------------------------------------------
# Capture endpoints
# ---------------------------------------------------------------------------

@router.get("/api/captures")
async def list_captures(
    request: Request, limit: int = 50, offset: int = 0, matched: str = None
) -> dict:
    """Return recent captures, optionally filtered by match status."""
    store = request.app.state.capture_store
    if matched == "true":
        captures = store.list(limit=limit, offset=offset, matched_only=True)
    elif matched == "false":
        captures = store.list(limit=limit, offset=offset, unmatched_only=True)
    else:
        captures = store.list(limit=limit, offset=offset)
    return {"captures": captures}


@router.get("/api/captures/{capture_id}")
async def get_capture(request: Request, capture_id: int) -> dict:
    """Return a single capture by ID, including full point data."""
    store = request.app.state.capture_store
    capture = store.get(capture_id)
    if capture is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return capture


@router.delete("/api/captures")
async def clear_captures(request: Request) -> dict:
    """Delete all captures and return the count removed."""
    store = request.app.state.capture_store
    count = store.clear()
    return {"cleared": count}


@router.put("/api/settings/captures")
async def update_captures_settings(request: Request) -> dict:
    """Update capture retention settings at runtime."""
    body = await request.json()
    store = request.app.state.capture_store
    if "max_captures" in body:
        store.set_max(int(body["max_captures"]))
    return {"max_captures": store._max}


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
