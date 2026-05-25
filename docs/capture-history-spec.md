# Capture history + dwell trimming — spec

## Overview

Three additions:
1. **Capture history**: ring buffer of every completed gesture attempt (raw
   points + match result), saved to disk, configurable retention.
2. **Dwell trimming**: preprocessing step that removes near-stationary
   clusters at the start and end of a gesture before matching.
3. **Web UI viewer**: page showing recent captures with SVG previews,
   match results, and filtering.

## Capture history

### Data model

Each capture records:
```json
{
  "id": 42,
  "timestamp": "2026-05-25T12:00:00+00:00",
  "raw_points": [{"x": 0.3, "y": 0.5, "t": 0.0}, ...],
  "point_count": 35,
  "duration_s": 1.2,
  "match_result": {
    "matched": true,
    "gesture_name": "lumos",
    "confidence": 0.82,
    "distance": 0.45
  },
  "trimmed_points": 4
}
```

### Storage: src/magicwand/captures.py

**CaptureStore class:**
```python
class CaptureStore:
    def __init__(self, captures_dir: Path, max_captures: int = 200):
        """Ring buffer of gesture captures on disk."""

    def add(self, raw_points, match_result, trimmed_count) -> int:
        """Add a capture. Returns its ID. Evicts oldest if over max."""

    def list(self, limit=50, offset=0, matched_only=False) -> list[dict]:
        """List recent captures (newest first)."""

    def get(self, capture_id: int) -> dict | None:
        """Get a single capture by ID."""

    def clear(self) -> int:
        """Clear all captures. Returns count deleted."""

    def set_max(self, max_captures: int):
        """Update retention limit. Evicts if current count exceeds new max."""
```

Storage format: single JSONL file `captures/history.jsonl`. Ring buffer
implemented by rewriting the file when it exceeds max (or simpler: keep
all in memory + flush periodically, with a load-on-startup from the file).

Actually, simplest correct approach: keep a list in memory, append on add,
evict from front when over max. Periodically (or on shutdown) write to file.
Load from file on startup.

### Config

```toml
[captures]
directory = "captures"
max_captures = 200
```

Configurable via Admin page (PUT /api/settings/captures).

### Integration with GestureWatcher

After `_attempt_match()` completes, call:
```python
capture_store.add(
    raw_points=self._points,
    match_result=result,
    trimmed_count=num_trimmed_points,
)
```

This happens in the camera thread (sync), so CaptureStore.add() must be
thread-safe.

### API endpoints

- `GET /api/captures?limit=50&offset=0&matched=true` — list captures
- `GET /api/captures/{id}` — get single capture with full point data
- `DELETE /api/captures` — clear all captures
- `PUT /api/settings/captures` — update max_captures

## Dwell trimming

### Algorithm

A "dwell" is a cluster of consecutive points where the wand isn't moving
significantly. Detect and remove these from the start and end.

**Speed-based detection:**
1. For each point, compute speed = distance to next point / time delta
2. A point is "dwelling" if its speed < `dwell_speed_threshold`
3. Trim leading dwell points (from start, until speed exceeds threshold)
4. Trim trailing dwell points (from end, backwards, until speed exceeds threshold)
5. If trimming would remove ALL points, keep the original (don't trim to empty)
6. Require at least `min_gesture_points` remaining after trim

**Default parameters:**
- `dwell_speed_threshold`: 0.05 (normalized units per second — at 640px
  width, this is ~32px/s, meaning movement under ~3% of frame width per
  second is considered stationary)
- Applied before the existing preprocessing (resample → center → scale → rotate)

### Implementation location

Add to `src/magicwand/matching.py`:
```python
def trim_dwells(points: list[GesturePoint], speed_threshold: float = 0.05) -> list[GesturePoint]:
    """Remove near-stationary points from start and end of gesture."""
```

Called in GestureWatcher._attempt_match() before preprocess().

### Config

Add to MatchingConfig:
```python
dwell_speed_threshold: float = 0.05
dwell_trim_enabled: bool = True
```

## Web UI: Captures viewer

### templates/captures.html

Page at `GET /captures`:
- Table/list of recent captures, newest first
- Each row: timestamp, point count, duration, match result (name + confidence or "no match"), SVG mini-preview
- Click to expand: full SVG path, raw point count before/after trimming
- Filter buttons: All | Matched | Unmatched
- "Clear History" button
- Retention setting display (current max, with edit)

### Navigation

Add "Captures" link to the nav bar (between Gestures and Admin).

### API

Uses existing endpoints:
- GET /api/captures for list
- GET /api/captures/{id} for detail

## Test specs

### Unit: tests/unit/test_captures.py
- test_add_and_list — add 3 captures, list returns them newest-first
- test_ring_buffer_evicts — set max=5, add 7, only 5 remain (newest)
- test_persistence — add captures, create new store on same dir, data loads

### Unit: tests/unit/test_dwell_trim.py
- test_trim_leading_dwell — 5 stationary points + 20 moving → trimmed to 20
- test_trim_trailing_dwell — 20 moving + 5 stationary → trimmed to 20
- test_trim_both — dwell at start and end, both removed
- test_no_trim_when_all_moving — all points above threshold, nothing trimmed
- test_no_trim_to_empty — all points are dwelling, keep original
- test_speed_threshold — points just above/below threshold behave correctly

### E2E: tests/e2e/test_captures_api.py
- test_captures_list_empty — initially empty
- test_captures_page_loads — GET /captures returns 200
