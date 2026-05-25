# Phase 6: Training UX polish — detailed spec

## Overview

Build the multi-sample gesture training workflow in the web UI. Users name a
gesture, record 3-5 samples with live camera feedback, review/accept each
sample visually, and test the trained gesture before committing.

## Web UI pages

### templates/gestures.html — Gesture list page

Accessible at `GET /gestures`.

Layout:
- Header: "Gestures" + "New Gesture" button
- Grid/list of gesture cards, each showing:
  - Gesture name
  - Sample count (e.g., "3 samples")
  - Miniature SVG preview of the first sample's path
  - Action status indicator (configured / not configured)
  - "Edit" and "Delete" buttons
- Empty state: "No gestures trained yet. Create one to get started."

### templates/train.html — Training wizard page

Accessible at `GET /train?name=<gesture_name>` (for new or existing gestures).

**Step 1: Name** (only for new gestures)
- Text input for gesture name
- Validation feedback (lowercase, hyphens, 1-30 chars)
- "Next" button

**Step 2: Record samples**
- Live camera feed (MJPEG stream)
- Sample counter: "Sample 1 of 5"
- Recording controls:
  - "Record" button → starts recording, button changes to "Stop"
  - Visual indicator on the feed border (red glow/border during recording)
  - Point counter during recording
- After recording stops (manual or auto):
  - Show the captured path as SVG overlay next to the feed
  - "Accept" / "Retry" buttons
  - If accepted, increment sample counter
  - If retried, clear and record again
- Minimum 3 samples required, "Save" button appears after 3
- Maximum 5 samples

**Step 3: Review & save**
- Show all accepted samples overlaid on a single SVG (different colors/opacity)
- "Save & Test" button → saves the gesture, transitions to test mode
- "Save" button → saves and returns to gesture list

**Test mode** (optional, after save):
- Live camera feed with matching active
- "Perform your gesture now" prompt
- Shows match result: gesture name, confidence score, success/fail indicator
- "Done" button returns to gesture list

### templates/gesture-detail.html — Gesture detail/edit page

Accessible at `GET /gesture/<name>`.

Shows:
- Gesture name (with rename option? — skip for now)
- All samples as individual SVG paths with "Remove" button each
- "Add more samples" button → goes to train page
- Action configuration section:
  - Preset dropdown (from Homebridge presets)
  - URL field (auto-filled from preset, editable)
  - Method dropdown (GET/POST/PUT)
  - Headers textarea (JSON)
  - Body textarea
  - "Test" button → fires the action
  - "Save Action" button
- "Delete Gesture" button (with confirmation)

## SVG gesture rendering

**JavaScript function `renderGestureSVG(points, options)`:**
- Takes an array of {x, y} points (normalized 0-1)
- Renders as an SVG path in a viewBox="0 0 1 1"
- Stroke: configurable color, default green (#22c55e)
- Stroke-width: 0.02 (relative to viewBox)
- Fill: none
- Start point: small circle marker
- Options: width, height, color, strokeWidth

Place this in a shared JS file: `static/js/gestures.js`

## API additions

### GET /gestures — serves gestures.html
### GET /train — serves train.html
### GET /gesture/{name} — serves gesture-detail.html

These are page routes (return HTML), not API routes.

The pages use the existing API endpoints (fetch from JS):
- GET /api/gestures
- POST /api/gestures
- DELETE /api/gestures/{name}
- POST /api/recording/start
- POST /api/recording/stop
- GET /api/recording/status
- POST /api/gestures/{name}/samples
- PUT /api/gestures/{name}/action
- POST /api/gestures/{name}/action/test
- GET /api/homebridge/presets

## Frontend JavaScript

### static/js/train.js

Handles the training wizard logic:
- Polls recording status during recording (every 200ms)
- Fetches the sample on stop
- Renders SVG preview of each sample
- Manages the sample collection state
- Submits samples to the API
- Handles the test mode

### static/js/gestures.js

Shared utilities:
- `renderGestureSVG()` — renders a gesture path as SVG
- `fetchJSON()` — wrapper around fetch with JSON parsing and error handling
- `formatConfidence()` — formats 0-1 as percentage

### static/js/gesture-detail.js

Handles the detail page:
- Load and display gesture data
- Action form management (presets, save, test)
- Sample removal

## Navigation

Add a simple nav bar to all pages:
- "magicwand" logo/home link (left)
- "Feed" | "Gestures" links (right)

Update index.html to include the nav bar.

## Test specs

### E2E: tests/e2e/test_training_ui.py

- `test_gestures_page_loads` — GET /gestures returns 200, HTML contains "Gestures"
- `test_train_page_loads` — GET /train?name=test returns 200, HTML contains MJPEG stream
- `test_gesture_detail_page_loads` — create gesture via API, GET /gesture/test-spell returns 200
- `test_training_workflow_api` — full API-driven workflow: create gesture → start recording → stop → add sample → verify gesture has 1 sample
