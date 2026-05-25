# Phase 8: Settings + polish — detailed spec

## Overview

Add a settings page for runtime configuration, system info display,
responsive CSS refinements, and production hardening.

## Settings page

### templates/settings.html

Accessible at `GET /settings`.

Sections:

**Detection settings:**
- Threshold slider (0-255, current value displayed)
- Min area input
- Max area input
- Blur kernel dropdown (3, 5, 7, 9)
- Trail length input
- "Apply" button → PUT /api/settings/detection
- Changes take effect immediately (no restart needed)

**Matching settings:**
- Distance threshold input (0.5 - 5.0, step 0.1)
- Min confidence input (0.0 - 1.0, step 0.05)
- Gap timeout input (0.1 - 2.0)
- Cooldown time input (0.5 - 10.0)
- Min gesture points input (5 - 50)
- "Apply" button → PUT /api/settings/matching

**Homebridge settings:**
- Host input
- Port input
- (Presets are in config.toml, display-only here)

**System info (display-only):**
- Uptime
- CPU temperature (if available via /sys/class/thermal)
- RAM usage (via psutil or /proc/meminfo)
- Disk usage
- Camera source (mock/picamera2)
- FPS (from detector)
- Python version
- App version

### API additions

`GET /api/system/info` — returns system stats:
```json
{
  "uptime_seconds": 3600,
  "cpu_temp_c": 45.2,
  "ram_used_mb": 180,
  "ram_total_mb": 416,
  "disk_used_gb": 2.5,
  "disk_total_gb": 15,
  "camera_source": "mock",
  "detection_fps": 24.3,
  "python_version": "3.13.5",
  "app_version": "0.1.0"
}
```

For Mac development: cpu_temp and some fields may be null (Pi-specific).
Use try/except and return null for unavailable metrics.

## Responsive CSS refinements

### Navigation bar (all pages)

Already added in Phase 6. Refine:
- Hamburger menu on mobile (< 640px)
- Active page indicator
- Smooth transitions

### Dark theme refinements

- Consistent color palette across all pages
- Form inputs: dark background (#1a1a2e), light text, purple accent on focus
- Buttons: primary (purple #7c3aed), danger (red #dc2626), secondary (gray)
- Cards: consistent border, padding, border-radius
- Status badges: green/yellow/red pills with subtle backgrounds
- Slider styling (for threshold etc.)

### Mobile optimizations

- Feed fills width on mobile, centered with max-width on desktop
- Gesture cards: single column on mobile, grid on desktop
- Settings form: full-width inputs on mobile
- Touch-friendly button sizes (min 44px tap target)
- Log scroll area: fixed height, scrollable

## Production hardening

### Error handling
- Camera disconnect: detect in CameraThread, attempt reconnect every 5s
- Action timeout: already handled (Phase 5), add visual indicator in log
- WebSocket disconnect: auto-reconnect in JS with exponential backoff

### systemd service refinements

Update `magicwand.service`:
- Add `StandardOutput=journal` for journald logging
- Add `Environment=PYTHONUNBUFFERED=1` for real-time logs
- Add resource limits (MemoryMax=400M for the Pi's constraints)

### Performance monitoring

- Add FPS warning in overlay when < 15 FPS (yellow) or < 10 FPS (red)
- Log warning when frame processing takes > 50ms

## Test specs

### E2E: tests/e2e/test_settings.py

- `test_settings_page_loads` — GET /settings returns 200, HTML contains form elements
- `test_system_info_endpoint` — GET /api/system/info returns JSON with expected keys
- `test_system_info_has_uptime` — uptime_seconds > 0
- `test_nav_links_present` — GET / returns HTML with nav links to /gestures and /settings

### E2E: tests/e2e/test_responsive.py (optional)

- If Playwright is set up: load page at 375px width (mobile), verify layout adapts
- Skip if Playwright not available
