# magicwand

A DIY interactive wand system inspired by the Wizarding World of Harry Potter at
Universal Studios. Wave a wand at a fixed point in a room, and something
magical happens — a light turns on, a curtain opens, a sound plays.

## How it works

The same principle as the Universal Studios wands: the wand tip is reflective,
and a camera tuned to a narrow band of infrared light tracks it against an
otherwise dark image. With ambient visible light filtered out and an infrared
ring light illuminating the scene, the bright tip stands out as a clean point
that's easy to track frame-to-frame. The resulting motion path is a *gesture*,
which can be matched against a library of trained gestures and mapped to an
action.

In this project, recognized gestures trigger actions on
[Homebridge](https://homebridge.io)-managed accessories via its REST API —
toggling lights, activating scenes (via dummy switches), or controlling any
HomeKit device exposed through Homebridge. A custom HTTP fallback supports
arbitrary URLs for non-Homebridge integrations.

## Hardware

- **Compute:** Raspberry Pi Zero 2 W
- **Camera:** OV5647-based IR-sensitive camera module (no IR-cut filter)
- **Optical filter:** 850 nm bandpass filter over the lens
- **Illumination:** Ring of 5 mm 850 nm IR LEDs around the camera
- **Storage:** 16 GB microSD card

## Software

A Python web app (FastAPI + OpenCV) running on the Pi, used for both
development and production:

- Live MJPEG camera feed with tip-detection overlay and time-fading trail
- Gesture training wizard: record samples, view color-coded segmentation
- Real-time gesture matching via DTW with confidence scoring
- Homebridge integration: auto-discover accessories, assign to gestures via
  dropdown (toggle/on/off), with custom HTTP fallback
- Event log with WebSocket live stream
- Admin page for tuning detection, matching, and Homebridge settings
- Capture history with visual debugging of segmentation
- Camera pause/resume from the feed page for development

### Running the app

```bash
cd /Users/jordan/Development/Personal/magicwand
source .venv/bin/activate
python -m magicwand.main
```

The web UI is at `http://localhost:8000`. The app will exit with a clear
error if port 8000 is already in use. To kill a stale instance first:

```bash
kill $(lsof -ti :8000) 2>/dev/null
```

### Development mode

During development the app runs on a Mac using the Studio Display webcam
with a phone flashlight LED as the bright point (`source = "auto"` in
config.toml). Deploy to the Pi via rsync.

## Architecture

```
Camera → Detector → GestureWatcher → Action Dispatch → Homebridge API
                        ↓                                  ↓
              Segmentation pipeline:              Toggle lights/switches
              1. Compute per-point speeds         or fire custom HTTP
              2. Segment at dwells
              3. Merge noise
              4. Filter trivial segments
              5. DTW match candidates
```

Key design decisions:
- **Directional gestures:** `rotate_to_indicative_angle` aligns the first
  point upward, so left-to-right and right-to-left are distinct gestures
- **Segmentation over trimming:** The system splits captures at dwell points
  rather than trimming ends, supporting multiple gestures in one capture
- **Strongest match wins:** When multiple gesture candidates survive filtering,
  all are matched and the lowest-distance result is used
- **Homebridge via Config UI X API:** Authentication (noauth or login),
  accessory discovery, and control via the built-in REST API — no extra
  plugins required. Dummy switches can trigger HomeKit scenes via automations

## Documentation

- [Implementation plan](docs/implementation-plan.md) — phased build plan
- [Gesture segmentation spec](docs/gesture-segmentation-spec.md) — segmentation
  algorithm design and parameters
- [Homebridge integration](docs/homebridge-integration.md) — API client,
  action format, and scene triggering via dummy switches

## Status

All 8 implementation phases complete plus Homebridge integration. Core
pipeline works end-to-end: camera → detect → track → segment → match →
toggle Homebridge accessory. 155 tests passing. Actively training gestures
and mapping them to HomeKit scenes.

## Repository

https://github.com/smudgeface/magicwand
