# Phase 5: Actions + Homebridge integration — detailed spec

## Overview

Close the loop: when a gesture is recognized, fire an HTTP POST to a
configured URL with a JSON payload. Each gesture has its own action config.
The web UI gets a form for configuring actions with Homebridge presets and
a test button.

## Action model

Stored inside each gesture's JSON file under the `action` key:

```json
{
  "action": {
    "url": "http://homebridge.local:8581/?accessoryId=light1&state=true",
    "method": "GET",
    "headers": {"Content-Type": "application/json"},
    "body": null,
    "timeout": 5.0
  }
}
```

Fields:
- `url` (str, required): the target URL
- `method` (str, default "GET"): HTTP method (GET, POST, PUT)
- `headers` (dict[str, str], default {}): extra headers
- `body` (str | None, default null): raw body string (JSON or otherwise)
- `timeout` (float, default 5.0): request timeout in seconds

## New files

### src/magicwand/actions.py

**ActionConfig dataclass:**
```python
@dataclass
class ActionConfig:
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    timeout: float = 5.0
```

**ActionResult dataclass:**
```python
@dataclass
class ActionResult:
    success: bool
    status_code: int | None
    response_body: str | None
    latency_ms: float
    error: str | None
```

**async dispatch_action(config: ActionConfig) -> ActionResult:**
- Use `httpx.AsyncClient` to make the HTTP request
- Measure latency (time before and after)
- Return ActionResult with status, body, latency
- On timeout or connection error: return ActionResult with success=False and error message
- Fire-and-forget semantics: caller doesn't need to await the result for the
  main loop, but the result is logged

**ActionDispatcher class:**
```python
class ActionDispatcher:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._last_result: ActionResult | None = None

    async def start(self):
        """Create the httpx client (call on app startup)."""
        self._client = httpx.AsyncClient()

    async def stop(self):
        """Close the httpx client (call on app shutdown)."""
        if self._client:
            await self._client.aclose()

    async def fire(self, config: ActionConfig) -> ActionResult:
        """Execute an action and return the result."""

    @property
    def last_result(self) -> ActionResult | None:
        """Most recent action result."""
```

### Homebridge presets

Stored in `config.toml`:

```toml
[homebridge]
host = "homebridge.local"
port = 8581

[[homebridge.presets]]
name = "Switch On"
method = "GET"
url_template = "http://{host}:{port}/?accessoryId={accessory_id}&state=true"

[[homebridge.presets]]
name = "Switch Off"
method = "GET"
url_template = "http://{host}:{port}/?accessoryId={accessory_id}&state=false"

[[homebridge.presets]]
name = "Scene Trigger"
method = "GET"
url_template = "http://{host}:{port}/?accessoryId={accessory_id}"
```

Presets use `url_template` with `{host}`, `{port}`, and `{accessory_id}` placeholders.
The API returns expanded presets with host/port filled in, leaving just
`{accessory_id}` for the user to fill in.

### src/magicwand/config.py additions

```python
@dataclass
class HomebridgePreset:
    name: str = ""
    method: str = "GET"
    url_template: str = ""

@dataclass
class HomebridgeConfig:
    host: str = "homebridge.local"
    port: int = 8581
    presets: list[HomebridgePreset] = field(default_factory=list)
```

Add to Config and update _load_config().

## Changes to existing files

### src/magicwand/gestures.py

Update the Gesture dataclass `action` field to be `dict | None` (it already
is). The action dict maps directly to ActionConfig fields. The GestureStore
already persists it in JSON.

Add a helper method:
```python
def set_action(self, name: str, action: dict | None) -> bool:
    """Set or clear the action for a gesture. Returns False if not found."""
```

### src/magicwand/main.py

- Create ActionDispatcher, start/stop it in lifespan
- Store on app.state.action_dispatcher
- Wire matching into action dispatch: when watcher returns a match,
  look up the gesture's action and fire it

The tricky part: the watcher runs in the camera thread (sync), but
action dispatch is async. Solution: when a match occurs, put the action
config into an asyncio-safe queue. A background asyncio task consumes
the queue and dispatches actions.

```python
import asyncio
import queue

action_queue: queue.Queue = queue.Queue()

# In camera thread (sync), after match:
if match.matched:
    gesture = store.get(match.gesture_name)
    if gesture and gesture.action:
        action_queue.put(gesture.action)

# Background async task:
async def action_worker(dispatcher, action_queue):
    while True:
        try:
            action_dict = await asyncio.get_event_loop().run_in_executor(
                None, action_queue.get, True, 0.5  # block with timeout
            )
            config = ActionConfig(**action_dict)
            result = await dispatcher.fire(config)
            logger.info("Action fired: %s → %d", config.url, result.status_code or 0)
        except queue.Empty:
            continue
        except Exception:
            logger.exception("Action worker error")
```

Start this task in the lifespan startup, cancel on shutdown.

### src/magicwand/camera.py

After watcher.feed() returns a match, check if matched and queue the action:
```python
if match_result and match_result.matched:
    gesture = self._gesture_store.get(match_result.gesture_name)
    if gesture and gesture.action:
        self._action_queue.put(gesture.action)
```

CameraThread needs access to gesture_store and action_queue. Add them as
constructor parameters.

### src/magicwand/web/routes.py

New/modified endpoints:

```python
@router.put("/api/gestures/{name}/action")
async def set_action(request: Request, name: str) -> dict:
    """Set or update the action for a gesture."""
    body = await request.json()
    store = request.app.state.gesture_store
    if not store.set_action(name, body):
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    return {"name": name, "action": body}

@router.delete("/api/gestures/{name}/action")
async def clear_action(request: Request, name: str) -> dict:
    """Clear the action for a gesture."""
    store = request.app.state.gesture_store
    if not store.set_action(name, None):
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    return {"name": name, "action": None}

@router.post("/api/gestures/{name}/action/test")
async def test_action(request: Request, name: str) -> dict:
    """Fire the gesture's action immediately (for testing)."""
    store = request.app.state.gesture_store
    g = store.get(name)
    if g is None:
        return JSONResponse({"error": "gesture not found"}, status_code=404)
    if g.action is None:
        return JSONResponse({"error": "no action configured"}, status_code=400)
    dispatcher = request.app.state.action_dispatcher
    from magicwand.actions import ActionConfig
    config = ActionConfig(**g.action)
    result = await dispatcher.fire(config)
    return {
        "success": result.success,
        "status_code": result.status_code,
        "latency_ms": round(result.latency_ms, 1),
        "error": result.error,
    }

@router.get("/api/homebridge/presets")
async def homebridge_presets(request: Request) -> list[dict]:
    """Return available Homebridge presets with host/port filled in."""
    from magicwand.config import get_config
    cfg = get_config()
    hb = cfg.homebridge
    presets = []
    for p in hb.presets:
        presets.append({
            "name": p.name,
            "method": p.method,
            "url_template": p.url_template.format(
                host=hb.host, port=hb.port, accessory_id="{accessory_id}"
            ),
        })
    return presets
```

## Test specs

### Unit: tests/unit/test_actions.py

- `test_action_config_defaults` — verify default method, headers, timeout
- `test_dispatch_success` — mock httpx to return 200, verify ActionResult
- `test_dispatch_timeout` — mock httpx to timeout, verify error in result
- `test_dispatch_connection_error` — mock httpx to raise, verify error
- `test_action_result_latency` — verify latency_ms is > 0

### E2E: tests/e2e/test_actions_api.py

- `test_set_action` — create gesture, PUT action, GET gesture detail, verify action set
- `test_clear_action` — set then DELETE action, verify action is null
- `test_test_action_no_gesture` — test action on nonexistent gesture → 404
- `test_test_action_no_action_configured` — create gesture without action, test → 400
- `test_homebridge_presets` — GET presets, verify returns list with expected structure
- `test_test_action_fires_request` — create gesture, set action pointing to a mock
  server (or just verify the dispatch path works by pointing at localhost health endpoint)

## Implementation notes

- `httpx` is already a dev dependency. Add it to the main dependencies in
  pyproject.toml since actions need it at runtime.
- The action_queue bridges sync (camera thread) and async (FastAPI) worlds.
  A stdlib `queue.Queue` polled from an async task via `run_in_executor` is
  the simplest correct approach.
- Log every action dispatch (success and failure) for Phase 7's event system.
- Don't retry failed actions — home automation is best-effort.
