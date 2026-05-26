# magicwand — project guide for Claude

See `README.md` for the project pitch and hardware list. This file captures
context and conventions that aren't obvious from the code.

## Context

Hobby project: a Harry Potter–style IR wand tracker that turns wand gestures
into HTTP POSTs against Homebridge to control HomeKit devices. Being built by
Jordan with his 11-year-old daughter as the primary user. "Fun to use" and
"fun to extend together" matter as much as code quality.

## Target device

Raspberry Pi Zero 2 W. Constraints to keep in mind:

- Quad-core Cortex-A53 @ 1 GHz, **512 MB RAM** — generous for embedded work,
  tight for anything that loads big ML models or buffers many frames.
- No Ethernet. Wi-Fi only. Plan for the Pi being on the home LAN, reachable
  by hostname (`magicwand.local` via mDNS) for development.
- Headless. Development happens over SSH and through the web app served from
  the Pi itself.

Prefer lightweight tooling. Avoid frameworks that assume 4+ GB RAM or pull
in a GPU.

## Architecture

- Camera capture and tip detection: Python, `picamera2` (Pi) or OpenCV webcam (Mac dev)
- Web app: FastAPI serving live MJPEG feed, training UI, captures, admin
- Gesture matching: DTW on preprocessed paths (resample → center → scale → rotate)
- Segmentation: speed-based dwell detection → linearity/curvature filtering
- Action dispatch: async HTTP via httpx on gesture match

### Segmentation is stable
The gesture segmentation logic (`segment_at_dwells`, `extract_gesture_candidates`,
linearity/curvature filters in `matching.py`) has been extensively tuned and
verified against real captures. **Do not modify without confirming a real,
observed issue with the user first.** See `docs/gesture-segmentation-spec.md`
for full documentation of the algorithm and pitfalls.

## Conventions

- Python 3. Use a venv inside the repo (`.venv/`).
- Keep dependencies minimal — every package is a thing to install on a
  resource-constrained device.
- Configuration in a single file (yaml or toml) at the repo root, not
  scattered env vars.

## Running the app locally

```bash
source .venv/bin/activate && python -m magicwand.main
```

**Before starting the app, kill any existing instance:**
```bash
kill $(lsof -ti :8000) 2>/dev/null; source .venv/bin/activate && python -m magicwand.main
```

The app has a port-conflict check that will exit with a clear error if port
8000 is already in use. If you see that error, kill the existing process first.
Multiple instances cause silent failures (the second binds to nothing and hangs).

## Documentation

- `docs/implementation-plan.md` — phased build plan. Read this before starting
  work on any phase. Each phase has explicit deliverables, technical notes,
  and test requirements.

## Key files

- `src/magicwand/matching.py` — segmentation + DTW matching engine
- `src/magicwand/camera.py` — camera thread with pause/resume
- `src/magicwand/main.py` — FastAPI app factory, startup, port check
- `src/magicwand/web/routes.py` — all API + page routes
- `config.toml` — all runtime parameters (detection, matching, camera)
- `gestures/` — stored gesture JSON files (training data)
- `captures/history.jsonl` — ring buffer of recent gesture attempts

## Out of scope (for now)

- Multi-user / auth on the web app — it runs on the home LAN.
- Persisting anything besides gesture definitions and config.
- Anything cloud-hosted.
