# Gesture segmentation — spec

## Overview

The segmentation pipeline extracts intentional gesture motion from a raw
capture that includes entry trails, dwells (pauses), and exit trails.

**Pipeline:**
```
raw captured points
  → compute per-point speeds (pixels/sec)
  → label each point as "dwelling" or "moving"
  → group into runs of same label
  → merge noise: short slow moves into dwells, short fast dwells back into motion
  → collapse adjacent same-label segments
  → discard dwell segments
  → filter trivial motion segments (too short, too linear, too little curvature)
  → remaining candidates → DTW matching (strongest match wins)
```

## Step 1: Speed computation

Speeds are computed between consecutive points in pixels/sec. Point
coordinates are normalized [0,1], so they're multiplied by `frame_width`
(default 640) to get pixel distances before dividing by time delta.

## Step 2: Dwell detection + segmentation

**Dwell definition:** A consecutive sequence of points where the speed
between frames is below `dwell_speed_threshold` (default 100 px/sec).

**Merge rules (order matters):**

1. **Short slow MOVE → dwell:** A moving segment shorter than
   `dwell_min_points` AND with avg speed below 2× the dwell threshold is
   noise within a pause — merge it into the surrounding dwell. A short but
   FAST motion (entry/exit trail) is preserved.

2. **Short fast DWELL → motion:** A dwell segment shorter than 3 points
   is a brief speed jitter mid-gesture — merge it back into motion. Real
   pauses (5+ points) are preserved as dwell boundaries.

3. **Collapse** adjacent same-label segments after merging.

**Parameters:**
- `dwell_speed_threshold`: 100 px/sec
- `dwell_min_points`: 10 (controls short-MOVE merge; must also be slow)

## Step 3: Filter trivial motion segments

After removing dwell segments, candidate motion segments are filtered:

1. **Too few points** — fewer than `min_gesture_points` (default 10) → discard

2. **Too short duration** — less than `min_segment_duration` (default 0.5s) → discard

3. **Near-perfect linearity** — PCA R² > 0.98 → discard regardless of
   curvature. Detection noise on a straight path can produce false curvature
   readings, so extremely linear paths are always trails.

4. **Linear + low curvature** — R² > `linearity_threshold` (default 0.95)
   AND total curvature < `min_curvature` (default π/2 = 1.57 rad) → discard.
   Requires BOTH conditions (AND logic) because a gesture may be elongated
   (high linearity) but still have significant direction changes.

**Key insight from tuning:** Entry/exit trails have linearity 0.99-1.0 and
curvature 0.2-1.4 rad. Real gestures have linearity 0.68-0.93 and curvature
3-15+ rad. The separation is clear.

## Step 4: Match candidates

Surviving segments are gesture candidates. For each candidate:
1. Preprocess: resample (32 pts) → center → normalize scale → rotate to indicative angle
2. Compare via DTW against all stored gesture samples
3. Compute confidence: `1 - (distance / distance_threshold)`
4. Apply checks: distance threshold, min confidence, ambiguity rejection

If multiple candidates survive (rare but valid — user drew two gestures),
all are matched and the **strongest** (lowest distance) successful match wins.

## Parameters (in config.toml `[matching]` section)

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `dwell_speed_threshold` | 100 | px/sec below which a point is "dwelling" |
| `dwell_min_points` | 10 | short MOVE merge threshold (also checks speed) |
| `min_gesture_points` | 10 | minimum points for a valid gesture |
| `min_segment_duration` | 0.5 | minimum seconds for a valid gesture |
| `linearity_threshold` | 0.95 | R² above this (with low curvature) = trail |
| `min_curvature` | 1.57 | radians; curvature below this (with high linearity) = trail |
| `distance_threshold` | 0.4 | DTW distance above this = no match |
| `min_confidence` | 0.7 | confidence below this = no match |
| `resample_count` | 32 | points after resampling for DTW |

## Training integration

When a gesture sample is recorded, the same segmentation pipeline runs on
the raw recording before storage. Only the best (longest) gesture candidate
is saved. This ensures training data is clean — no trails or dwells pollute
the stored samples.

## Pitfalls learned during development

- **Don't merge short dwells aggressively.** Using the same threshold for
  "merge short dwell into motion" and "merge short move into dwell" breaks
  segmentation. Real pauses at entry/exit boundaries are 5-8 points — a
  threshold of 10 swallows them. Use 3 for the dwell→motion merge.

- **Don't merge short fast moves into dwells.** An 8-point entry trail at
  500 px/sec is a real trail, not noise. The merge must check speed, not
  just point count.

- **Linearity alone rejects real gestures.** PCA linearity measures axis
  dominance, not straightness. An elongated S-curve scores 0.8+ linearity
  but has 4+ rad curvature. Always combine with curvature (AND logic).

- **Noise inflates curvature on straight paths.** Detection jitter along a
  straight trail accumulates ~2.5 rad of false curvature. The hard 0.98
  linearity cutoff handles this — if R² > 0.98, it's straight regardless.

- **`distance_threshold` must match normalized DTW scale.** After full
  preprocessing (center + scale + rotate), DTW distances are typically
  0.02-0.06 for same-gesture and 0.15-0.25 for different gestures.
  A threshold of 2.0 accepts everything; 0.4 with min_confidence 0.7
  gives effective cutoff of ~0.12.
