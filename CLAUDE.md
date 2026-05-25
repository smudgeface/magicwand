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

## Architecture sketch (subject to change)

- Camera capture and tip detection: Python, using `picamera2` + OpenCV.
- Web app: small Python service (FastAPI or similar) serving the live feed,
  debugging UI, and gesture-training UI.
- Gesture matching: TBD — likely a simple geometric/DTW approach before
  reaching for ML.
- Action dispatch: outbound HTTP POST to a per-gesture URL with a per-gesture
  JSON body.

## Conventions

- Python 3. Use a venv inside the repo (`.venv/`).
- Keep dependencies minimal — every package is a thing to install on a
  resource-constrained device.
- Configuration in a single file (yaml or toml) at the repo root, not
  scattered env vars.

## Out of scope (for now)

- Multi-user / auth on the web app — it runs on the home LAN.
- Persisting anything besides gesture definitions and config.
- Anything cloud-hosted.
