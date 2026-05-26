# Homebridge integration

## Overview

magicwand controls HomeKit devices through the Homebridge Config UI X REST
API. No additional Homebridge plugins are required for direct accessory
control. For triggering HomeKit scenes, use dummy switches with HomeKit
automations.

## Connection

Configure in `config.toml` or the Admin page:

```toml
[homebridge]
host = "192.168.20.4"
port = 8581
username = ""    # leave empty if auth is disabled
password = ""
```

The client authenticates on startup:
1. Try `POST /api/auth/noauth` (for instances with auth disabled)
2. Fall back to `POST /api/auth/login` with credentials
3. Cache JWT token, re-authenticate on expiry or 401

On macOS with Tailscale, httpx may be blocked by the network extension.
The client falls back to subprocess curl automatically.

## Accessory discovery

`GET /api/homebridge/accessories` returns accessories filtered to types
that have an "On" characteristic: **Lightbulb**, **Switch**, **Outlet**.

The Homebridge API only exposes accessories managed by Homebridge — not
native HomeKit devices paired directly to an Apple TV or HomePod.

## Action format

Gesture actions are stored in the gesture JSON file:

```json
{
  "type": "homebridge",
  "accessory_id": "unique-id-from-homebridge",
  "accessory_name": "Dining Table",
  "action": "toggle"
}
```

Supported actions: `toggle` (read current state, flip), `on`, `off`.

Legacy HTTP actions are still supported:

```json
{
  "type": "http",
  "url": "http://...",
  "method": "POST",
  "body": "{...}",
  "timeout": 5
}
```

Actions without a `type` field are treated as HTTP for backward
compatibility.

## Scene triggering via dummy switches

The Homebridge API doesn't expose HomeKit scenes. To trigger a scene:

1. Install the `homebridge-dummy` plugin in Homebridge
2. Create a regular switch (not stateless — stateless can't trigger
   automations) with auto-reset after 1 second
3. Name it descriptively, e.g. "Scene: Night Mode"
4. In Apple Home, create an automation: "When Scene: Night Mode turns on
   → run Night Mode scene"
5. In magicwand, assign the gesture to the dummy switch with "toggle"

The toggle fires the switch to on, the automation runs the scene, and the
switch auto-resets to off after 1 second — ready for the next trigger.

## API endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/homebridge/status` | GET | Connection state and host info |
| `/api/homebridge/connect` | POST | Test connection / authenticate |
| `/api/homebridge/accessories` | GET | List controllable accessories |
| `/api/settings/homebridge` | PUT | Update and persist connection settings |

## Architecture

```
Gesture matched → action dict on queue → action worker
    ↓                                        ↓
type == "homebridge"                   type == "http"
    ↓                                        ↓
HomebridgeClient.toggle()             ActionDispatcher.fire()
    ↓                                        ↓
PUT /api/accessories/{id}             HTTP request to URL
    ↓
event: ACTION_FIRED / ACTION_FAILED
```

`HomebridgeClient` is instantiated once at startup and shared via
`app.state.homebridge`. The action worker in `main.py` routes based on
`action_dict["type"]`.
