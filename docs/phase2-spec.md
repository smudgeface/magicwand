# Phase 2: Tip detection + debug overlay — detailed spec

## Overview

Add a detection pipeline that finds the brightest IR point in each frame,
tracks it across frames as a trail, and renders a full debug overlay onto
the MJPEG stream. This transforms the raw camera feed into a useful
development tool.

## Changes to existing files

### src/magicwand/camera.py

The `CameraThread` loop changes from:
```
capture frame → JPEG encode → buffer
```
to:
```
capture frame → run detection → render overlay → JPEG encode → buffer
```

The `CameraThread.__init__` will accept an optional `Detector` instance.
If provided, `detector.process(frame)` is called before encoding.

### config.toml additions

```toml
[detection]
threshold = 240          # brightness threshold (0-255) for binary mask
min_area = 20            # minimum contour area (pixels) to consider
max_area = 5000          # maximum contour area (pixels) to reject large blobs
blur_kernel = 5          # Gaussian blur kernel size (must be odd)
trail_length = 50        # number of recent positions to keep in the trail
```

## New files

### src/magicwand/detection.py

**DetectionResult dataclass:**
```python
@dataclass
class DetectionResult:
    detected: bool
    position: tuple[int, int] | None  # (x, y) pixel coordinates
    confidence: float                  # 0.0-1.0, brightness/threshold ratio
    contour_area: float               # area of the detected contour
```

**TrailPoint dataclass:**
```python
@dataclass
class TrailPoint:
    x: int
    y: int
    timestamp: float  # time.monotonic()
```

**Detector class:**
```python
class Detector:
    def __init__(self, config: DetectionConfig):
        self._config = config
        self._trail: deque[TrailPoint] = deque(maxlen=config.trail_length)
        self._fps_counter: FPSCounter  # rolling window FPS calculator

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, DetectionResult]:
        """Run detection on frame, return annotated frame + result."""

    @property
    def trail(self) -> list[TrailPoint]:
        """Current trail points (most recent last)."""

    @property
    def fps(self) -> float:
        """Current frames-per-second."""
```

**Detection pipeline (inside `process()`):**
1. Convert frame to grayscale: `cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)`
2. Apply Gaussian blur: `cv2.GaussianBlur(gray, (kernel, kernel), 0)`
3. Apply binary threshold: `cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)`
4. Find contours: `cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)`
5. Filter contours by area (min_area ≤ area ≤ max_area)
6. If valid contours found:
   - Pick the largest (or brightest — see notes)
   - Compute centroid via `cv2.moments()`
   - Calculate confidence: `peak_brightness / 255.0`
   - Append to trail
   - Return DetectionResult(detected=True, ...)
7. If no valid contours: return DetectionResult(detected=False, ...)

**Overlay rendering (separate method, called after detection):**
- **Green dot** at detected position (filled circle, radius 6, color (0, 255, 0))
- **Trailing path**: polyline through recent trail points, with alpha fade
  (most recent = bright green, oldest = dim). Since OpenCV doesn't support
  alpha on non-transparent images, draw segments with decreasing brightness:
  iterate through trail pairs, color interpolates from (0, 60, 0) to (0, 255, 0).
- **FPS counter**: top-left, white text, `f"{fps:.1f} FPS"`
- **Confidence**: top-right, `f"conf: {confidence:.2f}"` in green if > 0.6, yellow if 0.3-0.6, red if < 0.3 (or "no detection" in gray)
- **Threshold info**: bottom-left, `f"thr: {threshold}"` in dim text
- **Detection status**: bottom-right, "TRACKING" in green when detected,
  "SEARCHING" in yellow when not
- All text: `cv2.putText` with `FONT_HERSHEY_SIMPLEX`, scale 0.5-0.6

**FPSCounter (helper class):**
- Rolling window of last 30 frame timestamps
- `tick()` adds current time
- `fps` property returns frames/elapsed_time

### src/magicwand/config.py additions

**DetectionConfig dataclass:**
```python
@dataclass
class DetectionConfig:
    threshold: int = 240
    min_area: int = 20
    max_area: int = 5000
    blur_kernel: int = 5
    trail_length: int = 50
```

Add `detection: DetectionConfig` field to the top-level `Config` dataclass.
Update `_load_config()` to parse `[detection]` section.

### src/magicwand/web/routes.py additions

**PUT /api/settings/detection** — accepts JSON body with any subset of
detection params (threshold, min_area, max_area, blur_kernel, trail_length).
Updates the live Detector instance. Returns the current detection config.

The detector instance needs to be accessible from routes. Store it on
`app.state.detector`.

### src/magicwand/camera.py modifications

- `CameraThread.__init__` accepts an optional `detector: Detector | None`
- In the run loop, if detector is set: `frame, result = detector.process(frame)`
  before JPEG encoding
- Store latest `DetectionResult` on `app.state` or on the detector itself
  for the health/status endpoint to read

### MockCamera enhancement

Update the mock camera to generate a brighter, more realistic dot (brightness 255)
on a slightly noisy dark background (random noise 0-20 in grayscale, converted
to BGR). This gives the detection pipeline something realistic to work with.

## Test specs

### Unit: tests/unit/test_detection.py

- `test_detect_bright_dot` — create a black frame with a white circle at
  known position, run detection, verify position matches within 2px
- `test_detect_no_dot` — all-black frame, detection returns detected=False
- `test_detect_dim_dot_below_threshold` — gray circle (brightness 200) with
  threshold 240, should not detect
- `test_contour_area_filter_small` — very small dot (1px), below min_area,
  not detected
- `test_contour_area_filter_large` — huge white blob, above max_area,
  not detected
- `test_trail_accumulates` — process multiple frames with dot at different
  positions, verify trail grows
- `test_trail_max_length` — process more frames than trail_length, verify
  trail stays at max
- `test_fps_counter` — tick N times with known intervals, verify FPS calculation
- `test_overlay_renders_without_crash` — process frame, verify output frame
  is same shape (doesn't crash on drawing)
- `test_confidence_calculation` — dot with brightness 200, threshold 240,
  confidence should be ~0.78 (200/255)

### E2E: tests/e2e/test_detection_overlay.py

- `test_stream_contains_detection_overlay` — start app, grab a frame from
  the stream, verify it's visually different from a plain black frame
  (the overlay text and dot add pixels)
- `test_detection_settings_api` — PUT new threshold via API, verify response
  reflects the change

## Implementation notes

- The overlay is rendered directly onto the frame before JPEG encoding.
  This means all stream consumers see the same debug view. Later (Phase 8)
  we may add a toggle to serve raw vs annotated frames.
- Performance target: detection + overlay should take < 10ms per frame on
  Mac, < 30ms on Pi Zero (leaving headroom for the 33ms frame budget at 30 FPS).
- The trail fade effect doesn't need true alpha — just draw successive line
  segments with colors interpolated from dark to bright green.
- cv2.putText is ugly but lightweight. No need for PIL/Pillow for Phase 2.
