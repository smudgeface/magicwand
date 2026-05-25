# Phase 4: Gesture matching (DTW) — detailed spec

## Overview

Add real-time gesture recognition using Dynamic Time Warping (DTW). When the
system is not recording, it continuously watches for completed gestures
(tip appears → draws a shape → tip disappears) and matches them against
stored gesture samples. A match above a confidence threshold triggers
recognition.

## Algorithm: preprocessing + DTW

### Preprocessing pipeline

Every raw gesture path (list of `GesturePoint`) must be normalized before
comparison. This pipeline runs on both stored samples and live captures:

1. **Resample to fixed length (N=32 points)** by arc-length:
   - Calculate total path length (sum of Euclidean distances between consecutive points)
   - Place 32 points equally spaced along the path
   - Interpolate x, y at each resampled position
   - This handles speed normalization (same shape drawn fast/slow → same points)

2. **Center to origin:**
   - Compute centroid (mean x, mean y)
   - Subtract centroid from all points
   - Result: path is centered at (0, 0)

3. **Normalize scale:**
   - Find the bounding box of the centered path
   - Scale so the larger dimension (width or height) = 1.0
   - Preserves aspect ratio

4. **Rotation alignment (indicative angle):**
   - Compute the angle from the centroid to the first point
   - Rotate all points so this angle points "up" (toward -y, i.e., angle = -π/2)
   - This provides rotational invariance — the same gesture drawn at
     different arm angles will be aligned

Output: a list of 32 `(x, y)` tuples, centered, scaled, rotation-aligned.

### DTW matching

Compare two preprocessed paths using Dynamic Time Warping:

```python
def dtw_distance(path_a: list[tuple], path_b: list[tuple]) -> float:
    """Compute DTW distance between two preprocessed paths."""
    n, m = len(path_a), len(path_b)
    # cost matrix (n+1) x (m+1), initialized to infinity
    # DTW recurrence: cost[i][j] = dist(a[i], b[j]) + min(cost[i-1][j], cost[i][j-1], cost[i-1][j-1])
    # Return cost[n][m]
```

Since N=32, the cost matrix is 32×32 = 1024 cells. Trivially fast even
on the Pi Zero.

Distance metric for individual points: Euclidean distance
`sqrt((ax - bx)^2 + (ay - by)^2)`.

### Matching engine

**GestureWatcher class** — monitors the detection stream for completed gestures:
- Tracks state: IDLE (no tip), TRACKING (tip visible, accumulating points),
  COOLDOWN (just matched, waiting before next recognition)
- On each frame:
  - If tip detected and state is IDLE: transition to TRACKING, start collecting points
  - If tip detected and state is TRACKING: append point
  - If tip lost and state is TRACKING:
    - If tip lost for > gap_timeout (0.5s): gesture is complete → run matching
    - Brief losses (< gap_timeout): keep tracking (allows flicker)
  - If state is COOLDOWN: wait for cooldown_time (2.0s) then return to IDLE
- Minimum gesture length: 10 points (reject very short motions)

**Matching flow** (when gesture is complete):
1. Preprocess the captured path
2. For each stored gesture, for each sample:
   - Preprocess the sample (cache this on load or first match)
   - Compute DTW distance
3. For each gesture: score = min distance across its samples
4. Best match = gesture with lowest score
5. If best score < distance_threshold (configurable, default 2.0):
   - Confidence = 1.0 - (score / distance_threshold), clamped to [0, 1]
   - If confidence > min_confidence (default 0.6): MATCH
   - Check ambiguity: if 2nd best score is within 20% of best → reject (ambiguous)
6. If no match: reject

## New files

### src/magicwand/matching.py

**preprocess(points: list[GesturePoint], num_points: int = 32) -> list[tuple[float, float]]:**
- Resample, center, scale, rotate as described above
- Input: GesturePoint list (with x, y in [0,1] normalized coords)
- Output: list of (x, y) tuples, preprocessed

**resample(points, n) -> list[tuple[float, float]]:**
- Resample by arc-length to n equally-spaced points

**center(points) -> list[tuple[float, float]]:**
- Subtract centroid

**normalize_scale(points) -> list[tuple[float, float]]:**
- Scale so max dimension = 1.0

**rotate_to_indicative_angle(points) -> list[tuple[float, float]]:**
- Rotate so first-to-centroid angle is -π/2 (up)

**dtw_distance(a, b) -> float:**
- Classic DTW with Euclidean point distance
- Returns the total accumulated distance (not normalized by path length)
  Actually, normalize by dividing by (n + m) to make distance scale-independent

**MatchResult dataclass:**
```python
@dataclass
class MatchResult:
    matched: bool
    gesture_name: str | None
    confidence: float
    distance: float
    all_scores: dict[str, float]  # gesture_name → best distance
```

**GestureWatcher class:**
```python
class GestureWatcher:
    def __init__(self, gesture_store: GestureStore, config: MatchingConfig):
        self._store = gesture_store
        self._config = config
        self._state: WatcherState  # IDLE, TRACKING, COOLDOWN
        self._points: list[GesturePoint] = []
        self._tip_lost_time: float | None = None
        self._cooldown_until: float = 0.0
        self._preprocessed_cache: dict[str, list[list[tuple]]] = {}
        self._last_match: MatchResult | None = None

    def feed(self, detection: DetectionResult, timestamp: float, frame_width: int, frame_height: int) -> MatchResult | None:
        """Feed a detection result. Returns MatchResult when a gesture is completed and matched."""

    def _attempt_match(self) -> MatchResult:
        """Preprocess captured points and match against stored gestures."""

    def invalidate_cache(self, gesture_name: str | None = None):
        """Clear preprocessed cache (call when gestures are modified)."""

    @property
    def state(self) -> WatcherState
    
    @property
    def last_match(self) -> MatchResult | None
```

**WatcherState enum:** IDLE, TRACKING, COOLDOWN

### src/magicwand/config.py additions

```python
@dataclass
class MatchingConfig:
    distance_threshold: float = 2.0
    min_confidence: float = 0.6
    gap_timeout: float = 0.5
    cooldown_time: float = 2.0
    min_gesture_points: int = 10
    resample_count: int = 32
```

## Changes to existing files

### config.toml

```toml
[matching]
distance_threshold = 2.0
min_confidence = 0.6
gap_timeout = 0.5
cooldown_time = 2.0
min_gesture_points = 10
resample_count = 32
```

### src/magicwand/main.py

- Create GestureWatcher with gesture_store and matching config
- Store on app.state.watcher
- Wire into CameraThread (similar to recorder)

### src/magicwand/camera.py

- CameraThread accepts optional `watcher` parameter
- In the loop, after detection (and recorder feed), call:
  `match = self._watcher.feed(result, timestamp, width, height)`
  Store latest match on the watcher for API access.

### src/magicwand/web/routes.py

- `GET /api/matching/status` — returns watcher state, last match result
- `PUT /api/settings/matching` — update matching config

### src/magicwand/gestures.py

- When gestures are modified (add_sample, remove_sample, delete), notify
  the watcher to invalidate its cache. Add an optional callback hook:
  `GestureStore.on_change: Callable | None`

## Test specs

### Unit: tests/unit/test_matching.py

- `test_preprocess_resample_count` — preprocess 100 points → 32 output points
- `test_preprocess_centering` — preprocessed path has centroid at ~(0, 0)
- `test_preprocess_scale` — preprocessed path fits in [-0.5, 0.5] range
- `test_preprocess_rotation_invariance` — same shape rotated 45° has same
  preprocessed output (within tolerance)
- `test_dtw_identical_paths` — distance is 0 (or very close)
- `test_dtw_different_paths` — distance is > 0
- `test_dtw_similar_paths` — slightly perturbed path has small distance
- `test_match_known_gesture` — store a gesture with samples, perform the
  same gesture, verify it matches
- `test_reject_unknown_gesture` — perform a gesture not in the store,
  verify no match
- `test_watcher_state_transitions` — feed detections to simulate:
  idle → tracking → gesture complete → matching → cooldown → idle
- `test_watcher_cooldown` — after a match, watcher ignores new gestures
  until cooldown expires
- `test_ambiguity_rejection` — two very similar stored gestures, perform
  one, verify rejected due to ambiguity (or matched with lower confidence)

### E2E: tests/e2e/test_matching_api.py

- `test_matching_status_endpoint` — GET /api/matching/status returns valid JSON
- `test_matching_settings_update` — PUT new threshold, verify response
