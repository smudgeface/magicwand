"""Unit tests for magicwand.events — EventBus and EventType."""

from __future__ import annotations

import json
import queue
import pytest
from pathlib import Path

from magicwand.events import EventBus, EventType


# ---------------------------------------------------------------------------
# Basic subscribe / emit
# ---------------------------------------------------------------------------

def test_emit_and_subscribe() -> None:
    """subscribe() returns a queue that receives emitted events with correct type and data."""
    bus = EventBus(log_dir=None)
    q = bus.subscribe()

    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "lumos", "confidence": 0.95})

    event = q.get_nowait()
    assert event["type"] == EventType.GESTURE_RECOGNIZED.value
    assert event["data"]["name"] == "lumos"
    assert event["data"]["confidence"] == 0.95


def test_multiple_subscribers() -> None:
    """Two subscribers both receive the same emitted event."""
    bus = EventBus(log_dir=None)
    q1 = bus.subscribe()
    q2 = bus.subscribe()

    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "nox"})

    event1 = q1.get_nowait()
    event2 = q2.get_nowait()
    assert event1["type"] == EventType.GESTURE_RECOGNIZED.value
    assert event2["type"] == EventType.GESTURE_RECOGNIZED.value
    assert event1["data"] == event2["data"]


def test_unsubscribe() -> None:
    """After unsubscribe(), the queue no longer receives new events."""
    bus = EventBus(log_dir=None)
    q = bus.subscribe()
    bus.unsubscribe(q)

    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "expelliarmus"})

    with pytest.raises(queue.Empty):
        q.get_nowait()


# ---------------------------------------------------------------------------
# Log file writing
# ---------------------------------------------------------------------------

def test_log_file_written(tmp_path: Path) -> None:
    """Emitting an event with log_dir set creates events.jsonl with one JSON line."""
    bus = EventBus(log_dir=tmp_path)
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "accio"})
    bus.close()

    log_file = tmp_path / "events.jsonl"
    assert log_file.exists()

    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["type"] == EventType.GESTURE_RECOGNIZED.value


def test_event_serialization(tmp_path: Path) -> None:
    """Log entries contain timestamp (ISO format), type (string), and data (dict)."""
    bus = EventBus(log_dir=tmp_path)
    bus.emit(EventType.ACTION_FIRED, {"url": "http://homebridge.local/on", "status": 200})
    bus.close()

    log_file = tmp_path / "events.jsonl"
    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    entry = json.loads(lines[0])

    # timestamp is an ISO 8601 string (ends with +00:00 or Z)
    assert isinstance(entry["timestamp"], str)
    assert "T" in entry["timestamp"]  # ISO format contains literal 'T' separator

    # type is a plain string value of the enum
    assert isinstance(entry["type"], str)
    assert entry["type"] == "action_fired"

    # data is a dict matching what was emitted
    assert isinstance(entry["data"], dict)
    assert entry["data"]["url"] == "http://homebridge.local/on"
    assert entry["data"]["status"] == 200


# ---------------------------------------------------------------------------
# read_logs
# ---------------------------------------------------------------------------

def test_read_logs_returns_events(tmp_path: Path) -> None:
    """read_logs(limit=2) returns the last 2 of 3 emitted events."""
    bus = EventBus(log_dir=tmp_path)
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "first"})
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "second"})
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "third"})
    bus.close()

    results = bus.read_logs(limit=2)
    assert len(results) == 2
    assert results[0]["data"]["name"] == "second"
    assert results[1]["data"]["name"] == "third"


def test_read_logs_type_filter(tmp_path: Path) -> None:
    """read_logs(event_type=...) returns only events matching that type."""
    bus = EventBus(log_dir=tmp_path)
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "lumos"})
    bus.emit(EventType.ACTION_FIRED, {"url": "http://homebridge.local/on"})
    bus.emit(EventType.GESTURE_RECOGNIZED, {"name": "nox"})
    bus.close()

    results = bus.read_logs(event_type="action_fired")
    assert len(results) == 1
    assert results[0]["type"] == "action_fired"
    assert results[0]["data"]["url"] == "http://homebridge.local/on"


# ---------------------------------------------------------------------------
# No log_dir
# ---------------------------------------------------------------------------

def test_emit_without_log_dir() -> None:
    """EventBus(log_dir=None) does not crash on emit, and subscribe still works."""
    bus = EventBus(log_dir=None)
    q = bus.subscribe()

    # Should not raise
    bus.emit(EventType.SYSTEM_ERROR, {"message": "something went wrong"})

    event = q.get_nowait()
    assert event["type"] == "system_error"
    assert event["data"]["message"] == "something went wrong"

    # read_logs returns empty when there's no log dir
    assert bus.read_logs() == []
