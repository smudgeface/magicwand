# Phase 3: Gesture recording + storage — detailed spec

## Overview

Add the ability to record wand motions as named gestures, store them as
individual JSON files, and manage them via a REST API. The web UI gains a
gesture list page and a recording interface.

## Gesture data model

A gesture is defined by:
- **name**: short identifier (lowercase, hyphens allowed, e.g., "lumos")
- **samples**: list of recorded motion paths (each is a list of points)
- **action**: the HTTP action to fire (null until configured in Phase 5)

Each point in a sample:
```json
{"x": 0.45, "y": 0.62, "t": 0.0}
```
- `x`, `y`: normalized to [0, 1] (relative to frame dimensions)
- `t`: time in seconds since recording started

## File format

`gestures/<name>.json`:
```json
{
  "name": "lumos",
  "created_at": "2026-05-25T12:00:00",
  "samples": [
    [{"x": 0.1, "y": 0.2, "t": 0.0}, {"x": 0.15, "y": 0.25, "t": 0.05}, ...],
    [{"x": 0.11, "y": 0.19, "t": 0.0}, ...]
  ],
  "action": null
}
```

## New files

### src/magicwand/gestures.py

**GesturePoint dataclass:**
```python
@dataclass
class GesturePoint:
    x: float  # 0.0-1.0, normalized
    y: float  # 0.0-1.0, normalized
    t: float  # seconds since recording start
```

**GestureSample:** type alias for `list[GesturePoint]`

**Gesture dataclass:**
```python
@dataclass
class Gesture:
    name: str
    created_at: str  # ISO 8601
    samples: list[GestureSample]
    action: dict | None  # action config, null until Phase 5
```

**GestureStore class:**
```python
class GestureStore:
    def __init__(self, gestures_dir: Path):
        """Load all gestures from the directory."""
    
    def list(self) -> list[str]:
        """Return names of all gestures."""
    
    def get(self, name: str) -> Gesture | None:
        """Get a gesture by name."""
    
    def create(self, name: str) -> Gesture:
        """Create a new empty gesture. Raises ValueError if name exists."""
    
    def delete(self, name: str) -> bool:
        """Delete a gesture. Returns False if not found."""
    
    def add_sample(self, name: str, sample: GestureSample) -> int:
        """Add a sample to a gesture. Returns new sample count."""
    
    def remove_sample(self, name: str, index: int) -> bool:
        """Remove a sample by index. Returns False if not found."""
    
    def _save(self, gesture: Gesture) -> None:
        """Write gesture to its JSON file."""
    
    def _load(self, path: Path) -> Gesture:
        """Load a gesture from its JSON file."""
```

**Name validation:**
- 1-30 characters
- lowercase alphanumeric + hyphens only
- Must start with a letter
- Regex: `^[a-z][a-z0-9-]{0,29}$`

### src/magicwand/recorder.py

**RecordingState enum:** `IDLE`, `RECORDING`, `REVIEW`

**Recorder class:**
```python
class Recorder:
    def __init__(self, frame_width: int, frame_height: int):
        self._width = frame_width
        self._height = frame_height
        self._state = RecordingState.IDLE
        self._points: list[GesturePoint] = []
        self._start_time: float = 0.0
        self._tip_lost_time: float | None = None
        self._tip_lost_timeout = 0.5  # seconds

    @property
    def state(self) -> RecordingState:
        """Current recording state."""

    @property
    def current_sample(self) -> GestureSample | None:
        """The sample being recorded (or just recorded for review)."""

    def start_recording(self) -> None:
        """Transition to RECORDING state. Clears any previous data."""

    def feed(self, detection: DetectionResult, timestamp: float) -> None:
        """Feed a detection result into the recorder.
        
        When recording:
        - If detected: normalize coords and append to points
        - If not detected: track time since last detection
        - If tip lost for > timeout: auto-stop recording
        """

    def stop_recording(self) -> GestureSample | None:
        """Manually stop recording. Returns the sample or None if empty."""

    def discard(self) -> None:
        """Discard the current sample and return to IDLE."""

    def _normalize(self, x: int, y: int) -> tuple[float, float]:
        """Normalize pixel coords to [0, 1] range."""
```

**Auto-stop behavior:** When the tip is lost (detection.detected=False) for
longer than `_tip_lost_timeout` seconds during recording, automatically
transition to REVIEW state with whatever points were collected.

**Minimum sample requirement:** A sample must have at least 5 points to be
considered valid. If fewer, discard automatically on stop.

### src/magicwand/web/routes.py additions

**API endpoints:**
- `GET /api/gestures` — list all gestures (name, sample count, has_action)
- `POST /api/gestures` — create gesture (body: `{"name": "lumos"}`)
- `GET /api/gestures/{name}` — get full gesture detail
- `DELETE /api/gestures/{name}` — delete a gesture
- `POST /api/gestures/{name}/samples` — add a sample (body: sample point array)
- `DELETE /api/gestures/{name}/samples/{index}` — remove a sample
- `POST /api/recording/start` — begin recording
- `POST /api/recording/stop` — stop recording, return the sample
- `GET /api/recording/status` — current state + point count

**Recording integration with detection:**
The Recorder needs to receive detection results each frame. Wire it into
the camera thread loop: after detection, if recording, feed the result.
Store the Recorder on `app.state.recorder`.

### src/magicwand/camera.py changes

The CameraThread needs to call `recorder.feed(result)` after detection.
Add an optional `recorder` parameter (like detector), or expose a hook.

Simpler approach: have the Detector store its latest result, and have the
Recorder poll it. But timing matters — we want every frame's detection fed.

Best approach: CameraThread accepts an optional list of "frame observers"
that get called with (frame, detection_result) after each frame. The
Recorder registers as an observer.

Actually simplest: just pass the recorder to CameraThread alongside detector.
In the loop, after detection: `if self._recorder: self._recorder.feed(result, time.monotonic())`

### src/magicwand/main.py changes

- Create GestureStore with `gestures_dir` from config (default: `./gestures/`)
- Create Recorder with frame dimensions from config
- Pass recorder to CameraThread
- Store both on `app.state`

### config.toml additions

```toml
[gestures]
directory = "gestures"
```

### Web UI: templates/gestures.html

Simple list page:
- Shows all trained gestures in cards
- Each card: gesture name, sample count, miniature SVG path preview
- "New Gesture" button
- Click gesture → edit/delete options

### Web UI: templates/record.html

Recording page:
- Live camera feed (same MJPEG stream)
- Overlay showing recording state (IDLE/RECORDING/REVIEW)
- "Start Recording" button → "Stop" button while recording
- Point counter during recording
- After recording: show the captured path as SVG
- "Save" / "Discard" buttons during review

## Test specs

### Unit: tests/unit/test_gestures.py

- `test_create_gesture` — create, verify file exists
- `test_create_duplicate_raises` — create same name twice → ValueError
- `test_delete_gesture` — create then delete, verify file gone
- `test_add_sample` — add a sample, read back, verify points match
- `test_remove_sample` — add 2 samples, remove index 0, verify 1 remains
- `test_list_gestures` — create 3, list returns all names
- `test_name_validation_valid` — "lumos", "expecto-patronum", "a1" all valid
- `test_name_validation_invalid` — "Lumos", "123", "a_b", "" all rejected

### Unit: tests/unit/test_recorder.py

- `test_recorder_initial_state` — state is IDLE
- `test_start_recording` — state transitions to RECORDING
- `test_feed_while_recording` — feed detected points, verify current_sample grows
- `test_feed_normalizes_coordinates` — feed (320, 240) on 640x480 → (0.5, 0.5)
- `test_auto_stop_on_tip_lost` — feed non-detected for > 0.5s, state goes to REVIEW
- `test_manual_stop` — stop_recording returns sample
- `test_discard` — discard returns to IDLE, clears data
- `test_minimum_points` — fewer than 5 points → stop returns None

### E2E: tests/e2e/test_gestures_api.py

- `test_create_and_list_gesture` — POST create, GET list, verify it's there
- `test_delete_gesture` — create then delete, verify gone from list
- `test_add_sample_via_api` — POST a sample array, GET gesture, verify sample count
- `test_recording_status` — GET recording status, verify IDLE state
