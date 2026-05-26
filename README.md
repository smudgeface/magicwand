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

In this project, actions are HTTP POSTs to arbitrary URLs with a JSON payload.
That makes integration with home automation trivial — for our setup, gestures
will hit [Homebridge](https://homebridge.io) webhooks to control HomeKit
devices around the house.

## Hardware

- **Compute:** Raspberry Pi Zero 2 W
- **Camera:** OV5647-based IR-sensitive camera module (no IR-cut filter)
- **Optical filter:** 850 nm bandpass filter over the lens
- **Illumination:** Ring of 5 mm 850 nm IR LEDs around the camera
- **Storage:** 16 GB microSD card

## Software

A Python web app (FastAPI + OpenCV) running on the Pi, used for both
development and production:

- Live MJPEG camera feed with tip-detection overlay
- Gesture training wizard: record samples, view color-coded segmentation
- Real-time gesture matching via DTW with confidence scoring
- Action dispatch: fire HTTP requests on gesture match (Homebridge integration)
- Event log with WebSocket live stream
- Admin page for tuning all parameters at runtime
- Capture history with visual debugging of segmentation

### Development mode

During development the app runs on a Mac using the Studio Display webcam
with a phone flashlight LED as the bright point (`source = "auto"` in
config.toml). Deploy to the Pi via rsync.

## Architecture

```
Camera → Detector → GestureWatcher → Action Dispatch
                        ↓
              Segmentation pipeline:
              1. Compute per-point speeds
              2. Segment at dwells (speed < threshold)
              3. Merge noise (short slow jitter in motion, short fast jitter in dwell)
              4. Filter trivial segments (linearity, curvature, duration)
              5. DTW match surviving candidates against stored gestures
```

Key design decisions:
- **Directional gestures:** `rotate_to_indicative_angle` aligns the first
  point upward, so left-to-right and right-to-left are distinct gestures
- **Segmentation over trimming:** The system splits captures at dwell points
  rather than trimming ends, supporting multiple gestures in one capture
- **Strongest match wins:** When multiple gesture candidates survive filtering,
  all are matched and the lowest-distance result is used

## Documentation

- [Implementation plan](docs/implementation-plan.md) — phased build plan
- [Gesture segmentation spec](docs/gesture-segmentation-spec.md) — segmentation
  algorithm design and parameters

## Status

All 8 implementation phases complete. Core pipeline works end-to-end:
camera → detect → track → segment → match → fire action. 156 tests passing.
Currently tuning segmentation parameters and training gestures with real
hardware.

## Repository

https://github.com/smudgeface/magicwand
