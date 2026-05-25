# Phase 1: Project skeleton + live camera feed — detailed spec

## Overview

Build the foundational web app: a FastAPI server that captures frames from the
camera (or a mock source) and streams them to the browser as MJPEG. This gives
us the development scaffold everything else builds on.

## File structure to create

```
magicwand/
├── config.toml                  # app configuration
├── pyproject.toml               # project metadata + dependencies
├── requirements.txt             # pinned deps for Pi deployment
├── magicwand.service            # systemd unit file
├── src/
│   └── magicwand/
│       ├── __init__.py          # version string
│       ├── main.py              # FastAPI app factory + uvicorn entrypoint
│       ├── config.py            # config loading from TOML
│       ├── camera.py            # camera capture thread + frame buffer
│       └── web/
│           ├── __init__.py
│           ├── routes.py        # page routes (serves HTML)
│           ├── stream.py        # MJPEG streaming endpoint
│           ├── static/
│           │   └── css/
│           │       └── style.css
│           └── templates/
│               └── index.html   # main page with video feed
├── tests/
│   ├── conftest.py              # shared fixtures
│   ├── unit/
│   │   ├── test_config.py
│   │   └── test_camera.py
│   └── e2e/
│       └── test_stream.py
└── docs/
```

## Component specs

### config.toml

```toml
[server]
host = "0.0.0.0"
port = 8000

[camera]
width = 640
height = 480
fps = 30
# "picamera2" for real hardware, "mock" for development
source = "mock"

[camera.mock]
# Mock mode: generates synthetic frames (moving dot on black background)
dot_speed = 2.0  # pixels per frame
```

### src/magicwand/config.py

- Load config from `config.toml` at repo root (or path from `MAGICWAND_CONFIG` env var)
- Use `tomllib` (stdlib in Python 3.11+)
- Return a dataclass or Pydantic model with typed fields
- Validate required fields, apply defaults for optional ones
- Expose a module-level `get_config()` that caches the loaded config

### src/magicwand/camera.py

**CameraSource protocol:**
```python
class CameraSource(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_frame(self) -> numpy.ndarray: ...  # BGR format, HxWx3
```

**MockCamera:**
- Generates 640x480 black frames with a white circle (radius 10px) that
  moves in a figure-8 pattern
- Respects configured FPS (uses time.sleep between frames)
- Thread-safe: `get_frame()` returns the latest frame

**PiCamera:** (stub for now)
- Wraps picamera2 — will be implemented when hardware arrives
- Same interface as MockCamera

**FrameBuffer:**
- Holds the latest JPEG-encoded frame
- Camera thread captures frames, encodes to JPEG, writes to buffer
- Multiple stream consumers can read the latest frame concurrently
- Use `threading.Event` so consumers can wait for new frames
- Implementation: threading.Lock protecting a single `bytes` object + an Event

**CameraThread:**
- Background daemon thread
- Loop: capture frame → JPEG encode (cv2.imencode) → update FrameBuffer → notify waiters
- Graceful shutdown via threading.Event stop flag
- Logs FPS every 5 seconds for debugging

### src/magicwand/web/stream.py

**MJPEG endpoint: `GET /api/stream`**
- Returns `StreamingResponse` with content-type `multipart/x-mixed-replace; boundary=frame`
- Each frame: `--frame\r\nContent-Type: image/jpeg\r\n\r\n<jpeg bytes>\r\n`
- Reads from FrameBuffer, yielding frames as they arrive
- Must handle client disconnect gracefully (stop generator)
- Target: deliver frames as fast as the camera produces them

### src/magicwand/web/routes.py

- `GET /` — renders `index.html` template
- `GET /api/health` — returns `{"status": "ok", "uptime": <seconds>}`

### src/magicwand/web/templates/index.html

- Minimal, responsive HTML page
- Dark background (#1a1a2e or similar)
- Centered `<img src="/api/stream">` element that fills available width
  (max 640px on desktop, full-width on mobile)
- Title: "magicwand"
- Viewport meta tag for mobile
- Link to style.css

### src/magicwand/web/static/css/style.css

- Dark theme: dark navy/charcoal background, light text
- Card-style container for the video feed (subtle border, rounded corners)
- Responsive: works from 320px (iPhone SE) to desktop
- System font stack (no web font downloads)
- Minimal — just enough to look polished-casual, not a CSS framework

### src/magicwand/main.py

- `create_app()` factory function:
  - Load config
  - Create camera source (Mock or PiCamera based on config)
  - Start camera thread
  - Create FastAPI app
  - Mount static files
  - Include route and stream routers
  - Register shutdown handler to stop camera thread
- `if __name__ == "__main__"`: run uvicorn with config-driven host/port
- Also support: `uvicorn magicwand.main:app` for production

### pyproject.toml

```toml
[project]
name = "magicwand"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104",
    "uvicorn[standard]>=0.24",
    "jinja2>=3.1",
    "opencv-python-headless>=4.8",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.21",
    "httpx>=0.25",
    "playwright>=1.40",
]

[project.scripts]
magicwand = "magicwand.main:run"
```

### requirements.txt

Pinned versions of all dependencies for reproducible Pi deploys. Generate
from a working install, but start with unpinned for initial development.

### magicwand.service (systemd)

```ini
[Unit]
Description=magicwand gesture tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/magicwand
ExecStart=/home/admin/magicwand/.venv/bin/python -m magicwand.main
Restart=on-failure
RestartSec=5
Environment=MAGICWAND_CONFIG=/home/admin/magicwand/config.toml

[Install]
WantedBy=multi-user.target
```

## Test specs

### Unit: test_config.py
- Test loading a valid config.toml → correct dataclass fields
- Test missing file → clear error message
- Test missing required field → validation error
- Test defaults applied for optional fields

### Unit: test_camera.py
- Test MockCamera produces frames of correct dimensions
- Test FrameBuffer: write a frame, read it back
- Test FrameBuffer: multiple readers get the same frame
- Test FrameBuffer: reader blocks until frame available (with timeout)
- Test CameraThread starts and produces frames within 1 second

### E2E: test_stream.py
- Start the app (with mock camera) using httpx AsyncClient as test client
- GET /api/health → 200, body contains "ok"
- GET /api/stream → 200, content-type is multipart, first frame received
  within 1 second, frame is valid JPEG
- GET / → 200, HTML contains `<img` tag with stream URL
- (Playwright) Load page in headless browser, verify img element loads
  (naturalWidth > 0 after brief wait)

## Implementation notes

- The mock camera is not just for tests — it's the primary development mode
  until the OV5647 arrives. It should produce visually interesting frames
  (moving dot) so the stream is obviously "alive" when viewed in a browser.
- JPEG quality 80 is a good default — balances quality vs bandwidth on WiFi.
- The FrameBuffer doesn't need to be a ring buffer yet (we only keep the
  latest frame). If we later need historical frames for trail rendering,
  we'll expand it.
- No WebSocket yet — that comes in Phase 7 for the event log.
