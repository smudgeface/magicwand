# magicwand — implementation plan

Phased build plan for the web app. Each phase produces a working, testable
increment. Camera feed first (MVP priority), then layering detection, training,
matching, and actions on top.

---

## Phase 1: Project skeleton + live camera feed

**Goal:** Browser shows a live MJPEG stream from the Pi's camera at
`http://magicwand.local:8000`.

### Deliverables
- FastAPI app with uvicorn entrypoint
- `/` serves a minimal HTML page with an `<img>` tag pointing at the MJPEG endpoint
- `/api/stream` returns a multipart MJPEG stream from picamera2
- Camera runs in a dedicated thread, frames published to consumers via a
  thread-safe ring buffer
- `config.toml` with initial settings (port, resolution, framerate)
- Responsive layout (works on phone)
- `systemd` unit file for starting the app on boot
- Unit tests: config loading, ring buffer behavior
- E2E test: headless browser loads page, receives at least one frame

### Technical notes
- Resolution: 640×480 is plenty for gesture tracking at 2-3m and keeps CPU
  manageable on the Pi Zero
- Target framerate: 30 FPS capture, MJPEG stream may deliver fewer depending
  on client bandwidth
- picamera2 configure for raw IR-friendly mode (no auto white balance
  trickery, manual exposure control available)

### Dependencies
- `fastapi`, `uvicorn[standard]`, `jinja2` (templates)
- `picamera2` (system apt package, accessed via --system-site-packages venv)
- `opencv-python-headless` (for JPEG encoding of frames)
- `tomli` / `tomllib` (Python 3.11+ has it built-in)

---

## Phase 2: Tip detection + debug overlay

**Goal:** The brightest IR point is detected in each frame and drawn on the
stream with full debug info.

### Deliverables
- Detection pipeline: grayscale → threshold → find brightest contour → centroid
- Debug overlay rendered onto MJPEG frames:
  - Green dot at detected tip position
  - Fading trail (last N positions) showing motion path
  - FPS counter (top-left)
  - Detection confidence (brightness of peak vs threshold)
  - Threshold visualization (toggle: show binary mask)
- Configurable detection parameters in `config.toml` (threshold, min area,
  max area, blur kernel size)
- API endpoint to adjust detection params at runtime: `PUT /api/settings/detection`
- Unit tests: detection on synthetic frames (white dot on black), edge cases
  (no dot, multiple dots, dim dot)
- E2E test: feed a test image, verify overlay elements appear

### Technical notes
- OpenCV `cv2.threshold` + `cv2.findContours` — simple and fast enough for Pi Zero
- Trail stored as a deque of (x, y, timestamp) tuples, rendered as polyline
  with alpha fade
- With the 850nm bandpass filter, the scene should be mostly black except the
  wand tip — thresholding should be straightforward

---

## Phase 3: Gesture recording + storage

**Goal:** User can record wand motions and save them as named gesture samples.

### Deliverables
- Gesture recording state machine: idle → recording → review → save/discard
- Recording triggers: start when tip first detected after user clicks "Record",
  stop after tip lost for >0.5s or user clicks "Stop"
- Raw gesture data: array of `{x, y, t}` points (normalized time from start)
- Gesture file format: `gestures/<name>.json`
  ```json
  {
    "name": "lumos",
    "samples": [
      [{"x": 0.1, "y": 0.2, "t": 0.0}, ...],
      [{"x": 0.15, "y": 0.22, "t": 0.0}, ...]
    ],
    "action": null
  }
  ```
- API endpoints:
  - `GET /api/gestures` — list all gestures
  - `POST /api/gestures` — create new gesture (name only)
  - `POST /api/gestures/{name}/samples` — add a recorded sample
  - `DELETE /api/gestures/{name}/samples/{index}` — remove a sample
  - `DELETE /api/gestures/{name}` — delete gesture entirely
- Web UI: gesture list page, record page with live feed + recording indicator
- Coordinates normalized to [0, 1] range (relative to frame dimensions) for
  resolution independence
- Unit tests: recording state machine, file I/O, coordinate normalization
- E2E test: record flow (click record → wait → stop → verify file written)

---

## Phase 4: Gesture matching (DTW)

**Goal:** System recognizes performed gestures in real-time by comparing
against stored samples.

### Deliverables
- Preprocessing pipeline for raw gesture paths:
  1. Resample to fixed N points (e.g., 32) by arc-length
  2. Center to origin (subtract centroid)
  3. Normalize scale (fit into unit square)
  4. Optionally: rotation alignment (find optimal rotation via Procrustes)
- DTW implementation comparing two preprocessed paths
- Matching engine: runs continuously when not in training mode
  - Detect gesture boundary (tip appears → moves → disappears)
  - Preprocess captured path
  - Compare against all stored gesture samples
  - Best match below distance threshold → recognized
  - Reject if best match is above threshold (non-gesture)
- Speed normalization: resampling by arc-length inherently handles this
- Confidence score: `1 - (distance / threshold)` mapped to [0, 1]
- API endpoint: `GET /api/matching/status` (is matching active, last match)
- Configurable: threshold, min gesture length (points), max gesture duration
- Unit tests: preprocessing steps individually, DTW on known shapes,
  matching accuracy on synthetic gestures
- E2E test: perform a trained gesture, verify recognition event fires

### Technical notes
- DTW on 32-point 2D sequences is trivially fast even on Pi Zero (~1ms)
- Consider `fastdtw` package or just implement naive DTW (32×32 matrix is tiny)
- Rotation invariance via indicative angle (rotate so first→centroid vector
  points up) or Procrustes alignment
- Rejection: require confidence > 0.6 AND distance to 2nd-best match is
  meaningfully different (avoid ambiguous matches)

---

## Phase 5: Actions + Homebridge integration

**Goal:** Recognized gestures fire HTTP POSTs to configured URLs.

### Deliverables
- Action model: `{url, method, headers, body, timeout}`
- Action dispatch: async HTTP POST via `httpx` when gesture matched
- Per-gesture action config stored in gesture JSON file
- API endpoints:
  - `PUT /api/gestures/{name}/action` — set/update action
  - `POST /api/gestures/{name}/action/test` — fire the action immediately
- Homebridge presets:
  - Switch on: `{"url": "http://<host>:<port>/?accessoryId=<id>&state=true"}`
  - Switch off: same with `state=false`
  - Scene trigger: `{"url": "http://<host>:<port>/?accessoryId=<id>"}`
  - Presets stored in `config.toml` under `[homebridge]` section
- Web UI: action config form per gesture with URL, method, headers, JSON body
  fields + preset dropdown + "Test" button
- Response logging (status code, latency) attached to event log entry
- Unit tests: action dispatch (mock HTTP), preset expansion
- E2E test: configure action → test button → verify POST sent (mock server)

### Technical notes
- `httpx` for async HTTP — lighter than `requests`, native async
- Fire-and-forget with timeout (don't block detection loop)
- Log failures but don't retry (home automation is best-effort)

---

## Phase 6: Training UX polish

**Goal:** Smooth multi-sample training workflow with visual feedback.

### Deliverables
- Training wizard UI:
  1. Name the gesture
  2. "Record sample 1 of 5" — show live feed with recording indicator
  3. After recording: show the captured path overlaid on a card
  4. Accept/retry each sample
  5. After N samples: show all samples overlaid to visualize consistency
  6. "Save & Test" — commit then immediately enter test mode
- Test mode: perform the gesture, see if it matches (shows confidence score)
- Sample visualization: SVG rendering of normalized gesture paths
- Minimum 3 samples required, up to 5 recommended
- Edit existing gestures: add more samples, remove bad ones, rename
- Unit tests: wizard state machine, SVG path generation
- E2E test: full training flow end-to-end (record 3 samples → save → test)

---

## Phase 7: Logging + event stream

**Goal:** Real-time event visibility in the browser + persistent log file.

### Deliverables
- Event types: gesture_recognized, action_fired, action_failed, gesture_rejected,
  system_start, system_error
- Events carry: timestamp, type, gesture_name, confidence, action_url,
  response_status, latency_ms
- WebSocket endpoint: `ws://magicwand.local:8000/ws/events`
- Browser UI: scrolling live log below the camera feed (dashboard page)
  - Color-coded by event type
  - Filterable by type/gesture
- File output: `logs/events.jsonl` — one JSON object per line, append-only
- Log rotation: new file when current exceeds 10 MB, keep last 5
- API endpoint: `GET /api/logs?since=<timestamp>&type=<filter>` for historical query
- Unit tests: event serialization, rotation logic
- E2E test: trigger gesture → verify event appears in WebSocket + file

---

## Phase 8: Settings + polish

**Goal:** Runtime-configurable settings, responsive design, production hardening.

### Deliverables
- Settings page in web UI:
  - Detection params (threshold, blur, min/max area)
  - Matching params (confidence threshold, min points, max duration)
  - Camera params (exposure, gain — if manually controllable)
  - System info (uptime, CPU temp, RAM usage, disk usage)
- All settings changes persist to `config.toml`
- Responsive CSS: works well on iPhone SE through desktop
- Dark theme with accent colors (green/yellow/red for status)
- Error handling: camera disconnect recovery, action timeout handling
- Performance monitoring: warn in UI if FPS drops below threshold
- Systemd service: auto-start on boot, restart on crash
- Unit tests: settings validation, config round-trip
- E2E test: change setting → verify it takes effect on detection

---

## Cross-cutting concerns

### Testing strategy
- **Unit tests:** pytest, run on Mac (mock picamera2) and Pi
- **E2E tests:** Playwright (headless Chromium) driving the web UI
  - On Mac: use a mock camera feed (static images or video file)
  - On Pi: can test against real camera
- **CI-friendly:** tests must pass without a physical camera attached

### Project structure
```
magicwand/
├── config.toml
├── gestures/              # gesture JSON files
├── logs/                  # event log files
├── docs/                  # generated documentation
├── tests/
│   ├── unit/
│   └── e2e/
├── src/
│   └── magicwand/
│       ├── __init__.py
│       ├── main.py        # FastAPI app + uvicorn entrypoint
│       ├── camera.py      # picamera2 capture thread + ring buffer
│       ├── detection.py   # tip detection + trail tracking
│       ├── matching.py    # gesture preprocessing + DTW matching
│       ├── gestures.py    # gesture file I/O + data models
│       ├── actions.py     # HTTP action dispatch
│       ├── events.py      # event bus + logging
│       ├── config.py      # config loading + validation
│       └── web/
│           ├── routes.py  # API routes
│           ├── stream.py  # MJPEG streaming endpoint
│           ├── ws.py      # WebSocket event endpoint
│           ├── static/    # CSS, JS
│           └── templates/ # Jinja2 HTML templates
├── pyproject.toml         # project metadata + dependencies
├── requirements.txt       # pinned deps for Pi deployment
└── magicwand.service      # systemd unit file
```

### Development workflow
- Develop on Mac, test on Pi via SSH deploy
- `git push` from Mac → `git pull` on Pi → restart service
- Or: edit directly on Pi for quick iteration during camera work
