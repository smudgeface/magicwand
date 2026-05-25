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

## Software (planned)

A web app running on the Pi, intended for use during development and gesture
authoring:

- Live camera feed with tip-detection overlay
- Logging and debugging views
- Gesture training: record a new gesture, name it, associate it with a
  target URL + JSON payload
- Gesture playback / test runner

## Status

Early — hardware is being assembled and the Pi is being provisioned.

## Repository

https://github.com/smudgeface/magicwand
