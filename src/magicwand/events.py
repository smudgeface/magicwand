"""Event bus and logging for magicwand."""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import IO


class EventType(str, Enum):
    GESTURE_RECOGNIZED = "gesture_recognized"
    ACTION_FIRED = "action_fired"
    ACTION_FAILED = "action_failed"
    GESTURE_REJECTED = "gesture_rejected"
    SYSTEM_START = "system_start"
    SYSTEM_ERROR = "system_error"


@dataclass
class Event:
    timestamp: str  # ISO 8601
    type: str  # EventType value
    data: dict

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "type": self.type, "data": self.data}


class EventBus:
    def __init__(
        self,
        log_dir: Path | None = None,
        max_file_size: int = 10_000_000,
        max_files: int = 5,
    ):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._log_dir = log_dir
        self._max_file_size = max_file_size
        self._max_files = max_files
        self._log_file: Path | None = None
        self._log_handle: IO | None = None
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self._open_log_file()

    def subscribe(self) -> queue.Queue:
        """Create and return a new subscriber queue."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove a subscriber queue."""
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def emit(self, event_type: EventType, data: dict) -> None:
        """Emit an event. Thread-safe -- can be called from the camera thread."""
        event = Event(
            timestamp=datetime.now(timezone.utc).isoformat(),
            type=event_type.value,
            data=data,
        )
        event_dict = event.to_dict()

        # Notify subscribers (drop if queue is full -- don't block camera thread)
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(event_dict)
                except queue.Full:
                    pass  # subscriber is slow, drop event

        # Write to log file
        self._write_to_log(event_dict)

    def _write_to_log(self, event_dict: dict) -> None:
        """Append event as JSON line. Rotate if file exceeds max size."""
        if not self._log_dir:
            return
        with self._lock:
            if self._log_handle is None:
                self._open_log_file()
            if self._log_handle is None:
                return
            line = json.dumps(event_dict) + "\n"
            self._log_handle.write(line)
            self._log_handle.flush()
            # Check rotation
            if self._log_file and self._log_file.stat().st_size > self._max_file_size:
                self._rotate_log()

    def _open_log_file(self) -> None:
        """Open the current log file for appending."""
        if not self._log_dir:
            return
        self._log_file = self._log_dir / "events.jsonl"
        self._log_handle = open(self._log_file, "a", encoding="utf-8")

    def _rotate_log(self) -> None:
        """Rotate: events.jsonl -> events.1.jsonl, events.1 -> events.2, etc."""
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

        if not self._log_dir or not self._log_file:
            return

        # Shift existing rotated files
        for i in range(self._max_files - 1, 0, -1):
            src = self._log_dir / f"events.{i}.jsonl"
            dst = self._log_dir / f"events.{i + 1}.jsonl"
            if src.exists():
                if i + 1 >= self._max_files:
                    src.unlink()  # delete oldest
                else:
                    src.rename(dst)

        # Rotate current file to .1
        if self._log_file.exists():
            self._log_file.rename(self._log_dir / "events.1.jsonl")

        self._open_log_file()

    def read_logs(
        self,
        since: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Read historical log entries. Reads from the current log file."""
        if not self._log_dir:
            return []
        log_file = self._log_dir / "events.jsonl"
        if not log_file.exists():
            return []

        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since and entry.get("timestamp", "") < since:
                    continue
                if event_type and entry.get("type") != event_type:
                    continue
                entries.append(entry)

        # Return the most recent 'limit' entries
        return entries[-limit:]

    def close(self) -> None:
        """Close the log file handle."""
        with self._lock:
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None
