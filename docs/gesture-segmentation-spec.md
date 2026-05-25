# Gesture segmentation — spec

## Overview

Replace the current "entire capture = one gesture" model with intelligent
segmentation that extracts the actual gesture from entry/exit noise.

**Pipeline:**
```
raw captured points
  → segment at dwells (split into chunks)
  → discard dwell segments
  → filter trivial segments (linear, low curvature)
  → remaining candidates → DTW matching
```

## Step 1: Dwell detection + segmentation

**Dwell definition:** A consecutive sequence of N or more points where the
speed between frames is below `dwell_speed_threshold`.

**Parameters:**
- `dwell_speed_threshold`: 0.05 (normalized units/sec) — same as before
- `dwell_min_points`: 3 — minimum consecutive slow points to count as a dwell

**Algorithm:**
```python
def segment_at_dwells(points, speed_threshold, min_dwell_points) -> list[Segment]:
    """Split a point sequence into segments separated by dwells.
    
    Returns a list of Segment objects. Dwell segments are marked as such.
    """
    # 1. Compute per-point speeds
    # 2. Label each point as "moving" or "dwelling" based on speed
    # 3. Group consecutive same-label points into runs
    # 4. Merge short moving runs (< min_dwell_points) into adjacent dwells
    # 5. Return segments with their labels
```

**Segment dataclass:**
```python
@dataclass
class Segment:
    points: list[GesturePoint]
    is_dwell: bool
    avg_speed: float  # average speed within this segment
```

## Step 2: Filter trivial segments

After removing dwell segments, we have candidate motion segments. Filter
those that are too simple to be intentional gestures.

**Filters (applied to each non-dwell segment):**

1. **Too few points** — fewer than `min_gesture_points` (default 10) → discard

2. **Too short duration** — less than 0.2s → discard

3. **Linearity test** — fit a line via least squares, compute R².
   If R² > `linearity_threshold` (default 0.85) → discard.
   Entry/exit trails are nearly straight, gestures have curves.

4. **Low curvature** — compute total absolute angular change along the path.
   If total_angle_change < `min_curvature` (default π/2 = 90°) → discard.
   A straight or slightly curved path has low angular change; a gesture
   that loops, zigzags, or circles has high angular change.

**Parameters (in config):**
```python
linearity_threshold: float = 0.85   # R² above this = too linear
min_curvature: float = 1.57         # radians (π/2); total angle change below this = too simple
min_segment_duration: float = 0.2   # seconds
```

## Step 3: Match candidates

Surviving segments are gesture candidates. For each:
1. Apply existing preprocessing (resample → center → scale → rotate)
2. Run DTW against stored gestures
3. If match: fire action, emit event
4. If no match: reject (as before)

If multiple candidates survive in a single capture (unusual but possible),
process them in order. Stop after first match to avoid double-firing.

## Implementation

### Replace `trim_dwells` with `segment_gesture`

In `matching.py`, replace the old `trim_dwells` function with:

```python
def compute_speeds(points: list[GesturePoint]) -> list[float]:
    """Compute speed between consecutive points."""

def segment_at_dwells(points, speed_threshold, min_dwell_points) -> list[Segment]:
    """Split into dwell and motion segments."""

def linearity(points: list[GesturePoint]) -> float:
    """Compute R² of a linear fit. Returns 0-1 (1 = perfectly linear)."""

def total_curvature(points: list[GesturePoint]) -> float:
    """Sum of absolute angle changes between consecutive direction vectors."""

def extract_gesture_candidates(
    points: list[GesturePoint],
    speed_threshold: float,
    min_dwell_points: int,
    min_points: int,
    min_duration: float,
    linearity_threshold: float,
    min_curvature: float,
) -> list[list[GesturePoint]]:
    """Full pipeline: segment → filter → return candidate point lists."""
```

### GestureWatcher changes

`_attempt_match()` becomes:
```python
def _attempt_match(self) -> MatchResult:
    candidates = extract_gesture_candidates(
        self._points,
        speed_threshold=self._config.dwell_speed_threshold,
        min_dwell_points=3,
        min_points=self._config.min_gesture_points,
        min_duration=self._config.min_segment_duration,
        linearity_threshold=self._config.linearity_threshold,
        min_curvature=self._config.min_curvature,
    )
    
    if not candidates:
        return MatchResult(matched=False, ...)  # no viable candidates
    
    # Try each candidate (usually just one)
    for candidate in candidates:
        preprocessed = preprocess(candidate, self._config.resample_count)
        result = self._compare_against_store(preprocessed)
        if result.matched:
            return result
    
    # No candidate matched
    return MatchResult(matched=False, ...)
```

### Config additions

Add to MatchingConfig:
```python
linearity_threshold: float = 0.85
min_curvature: float = 1.57  # π/2
min_segment_duration: float = 0.2
dwell_min_points: int = 3
```

Remove `dwell_trim_enabled` (segmentation replaces the old trim approach).

### CaptureStore integration

Store additional data per capture:
- `segments_found`: number of total segments
- `candidates_found`: number after filtering
- `candidate_points`: list of the candidate(s) that were actually matched against

## Test specs

### Unit: tests/unit/test_segmentation.py

- `test_segment_at_dwells_basic` — dwell + motion + dwell → 3 segments
- `test_segment_single_motion` — all moving → 1 segment (not dwell)
- `test_linearity_straight_line` — points on a line → R² ≈ 1.0
- `test_linearity_circle` — points on a circle → R² low
- `test_curvature_straight` — straight path → low angle change
- `test_curvature_circle` — circular path → high angle change (~2π)
- `test_extract_candidates_filters_linear` — entry trail + gesture + exit trail
  → only gesture survives
- `test_extract_candidates_keeps_complex` — a loopy gesture survives all filters
- `test_real_scenario` — simulate: entry trail → dwell → gesture → dwell → exit trail.
  Verify exactly 1 candidate returned, matching the gesture portion.
