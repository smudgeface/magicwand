# Phase 7: Logging + event stream — detailed spec

## Overview

Add real-time event visibility via WebSocket and persistent log files.
Events stream to the browser for a live log view and are written to
JSONL files for offline review.

## Event model

**EventType enum:** gesture_recognized, action_fired, action_failed,
gesture_rejected, system_start, system_error

**Event dataclass:**
```python
@dataclass
class Event:
    timestamp: str        # ISO 8601
    type: EventType
    data: dict            # type-specific payload
```

Payloads by type:
- `gesture_recognized`: gesture_name, confidence, distance
- `action_fired`: gesture_name, url, status_code, latency_ms
- `action_failed`: gesture_name, url, error, latency_ms
- `gesture_rejected`: reason (too_few_points | low_confidence | ambiguous | no_match)
- `system_start`: camera_source, server_port
- `system_error`: message, component

## New files

### src/magicwand/events.py

**EventBus class:**
```python
class EventBus:
    def __init__(self, log_dir: Path, max_file_size: int = 10_000_000, max_files: int = 5):
        self._subscribers: list[asyncio.Queue] = []
        self._log_dir = log_dir
        self._log_file: Path | None = None
        self._log_handle: IO | None = None
        self._max_file_size = max_file_size
        self._max_files = max_files

    def subscribe(self) -> asyncio.Queue:
        """Create a new subscriber queue. Returns a queue that receives events."""

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscriber."""

    def emit(self, event_type: EventType, data: dict):
        """Emit an event to all subscribers and write to log file."""
        # Thread-safe: can be called from the camera thread

    def _write_to_log(self, event: Event):
        """Append event as JSON line. Rotate if needed."""

    def _rotate_log(self):
        """Rotate log file when it exceeds max size."""
```

Thread safety: `emit()` must be callable from the sync camera thread.
Use `threading.Lock` for the log file. For async subscribers, put events
into the queues (asyncio.Queue is thread-safe for put from sync code
when using `put_nowait`).

Actually — asyncio.Queue.put_nowait is NOT thread-safe. Use a different
approach: have the EventBus store events in a thread-safe deque, and have
the WebSocket handler poll it. Or simpler: use a callback pattern where
the camera thread calls emit(), which writes to the log file (sync, with
lock), and also sets a flag. The WebSocket handler periodically checks.

Best approach for simplicity: use `queue.Queue` (thread-safe stdlib) for
each subscriber. WebSocket handler wraps get() in run_in_executor.

### src/magicwand/web/ws.py

**WebSocket endpoint: `/ws/events`**
```python
@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    await websocket.accept()
    event_bus = websocket.app.state.event_bus
    q = event_bus.subscribe()
    try:
        while True:
            event = await asyncio.get_event_loop().run_in_executor(
                None, q.get, True, 1.0  # block with timeout
            )
            await websocket.send_json(event)
    except (WebSocketDisconnect, queue.Empty, Exception):
        pass
    finally:
        event_bus.unsubscribe(q)
```

### Dashboard event log (index.html update)

Add a scrolling event log section below the camera feed:
- Connected via WebSocket to `/ws/events`
- Each event rendered as a line: timestamp, type badge, details
- Color-coded: green for recognized, yellow for rejected, red for failed
- Auto-scrolls to bottom, max 100 visible entries
- Filter chips: All | Recognized | Actions | Errors

JavaScript in `static/js/events.js`:
- Connect WebSocket on page load
- Parse incoming events, render as DOM elements
- Auto-reconnect on disconnect (with backoff)

## Integration points

### Camera thread → EventBus

After a match result (in camera.py):
- `gesture_recognized` when matched
- `gesture_rejected` when not matched (with reason)

After action dispatch (in main.py action worker):
- `action_fired` on success
- `action_failed` on failure

On startup (in main.py lifespan):
- `system_start`

### API additions

- `GET /api/logs?since=<iso_timestamp>&type=<filter>&limit=<n>` — query historical log
- WebSocket `/ws/events` — live stream

## Log file format

`logs/events.jsonl`:
```json
{"timestamp":"2026-05-25T12:00:00","type":"gesture_recognized","data":{"gesture_name":"lumos","confidence":0.85,"distance":0.42}}
{"timestamp":"2026-05-25T12:00:01","type":"action_fired","data":{"gesture_name":"lumos","url":"http://...","status_code":200,"latency_ms":45.2}}
```

## Config additions

```toml
[logging]
directory = "logs"
max_file_size = 10000000
max_files = 5
```

## Test specs

### Unit: tests/unit/test_events.py

- `test_emit_and_subscribe` — subscribe, emit, verify event received
- `test_multiple_subscribers` — 2 subscribers both receive same event
- `test_unsubscribe` — unsubscribe, emit, verify no event received
- `test_log_file_written` — emit event, verify JSONL file has entry
- `test_event_serialization` — event has correct timestamp and type fields

### E2E: tests/e2e/test_events_api.py

- `test_logs_endpoint` — GET /api/logs returns list
- `test_websocket_receives_events` — connect WS, emit an event, verify received
