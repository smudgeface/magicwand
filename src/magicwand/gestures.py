from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,29}$")


@dataclass
class GesturePoint:
    x: float  # 0.0-1.0, normalized
    y: float  # 0.0-1.0, normalized
    t: float  # seconds since recording start


GestureSample = list[GesturePoint]


@dataclass
class Gesture:
    name: str
    created_at: str  # ISO 8601
    samples: list[GestureSample] = field(default_factory=list)
    action: dict | None = None


def validate_gesture_name(name: str) -> bool:
    """Check whether *name* is a valid gesture identifier."""
    return _NAME_PATTERN.match(name) is not None


class GestureStore:
    """File-based storage for gesture definitions.

    Each gesture is stored as a separate JSON file in *gestures_dir*.
    """

    def __init__(self, gestures_dir: Path) -> None:
        self._dir = gestures_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._gestures: dict[str, Gesture] = {}
        self.on_change: Callable[[str | None], None] | None = None
        # Load existing gesture files
        for path in sorted(self._dir.glob("*.json")):
            try:
                gesture = self._load(path)
                self._gestures[gesture.name] = gesture
            except (json.JSONDecodeError, KeyError, TypeError):
                # Skip malformed files
                continue

    def list(self) -> list[str]:
        """Return names of all gestures, sorted alphabetically."""
        return sorted(self._gestures.keys())

    def get(self, name: str) -> Gesture | None:
        """Get a gesture by name, or None if not found."""
        return self._gestures.get(name)

    def create(self, name: str) -> Gesture:
        """Create a new empty gesture.

        Raises ValueError if the name is invalid or already exists.
        """
        if not validate_gesture_name(name):
            raise ValueError(f"Invalid gesture name: {name!r}")
        if name in self._gestures:
            raise ValueError(f"Gesture already exists: {name!r}")

        gesture = Gesture(
            name=name,
            created_at=datetime.now(timezone.utc).isoformat(),
            samples=[],
            action=None,
        )
        self._gestures[name] = gesture
        self._save(gesture)
        if self.on_change:
            self.on_change(name)
        return gesture

    def delete(self, name: str) -> bool:
        """Delete a gesture. Returns False if not found."""
        if name not in self._gestures:
            return False
        del self._gestures[name]
        path = self._dir / f"{name}.json"
        if path.exists():
            path.unlink()
        if self.on_change:
            self.on_change(name)
        return True

    def add_sample(self, name: str, sample: GestureSample) -> int:
        """Add a recorded sample to a gesture.

        Returns the new total sample count.
        Raises ValueError if the gesture is not found.
        """
        gesture = self._gestures.get(name)
        if gesture is None:
            raise ValueError(f"Gesture not found: {name!r}")
        gesture.samples.append(sample)
        self._save(gesture)
        if self.on_change:
            self.on_change(name)
        return len(gesture.samples)

    def remove_sample(self, name: str, index: int) -> bool:
        """Remove a sample by index. Returns False if index out of range."""
        gesture = self._gestures.get(name)
        if gesture is None:
            return False
        if index < 0 or index >= len(gesture.samples):
            return False
        gesture.samples.pop(index)
        self._save(gesture)
        if self.on_change:
            self.on_change(name)
        return True

    def _save(self, gesture: Gesture) -> None:
        """Write gesture to its JSON file."""
        path = self._dir / f"{gesture.name}.json"
        data = {
            "name": gesture.name,
            "created_at": gesture.created_at,
            "samples": [
                [{"x": pt.x, "y": pt.y, "t": pt.t} for pt in sample]
                for sample in gesture.samples
            ],
            "action": gesture.action,
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    def _load(self, path: Path) -> Gesture:
        """Load a gesture from its JSON file."""
        data = json.loads(path.read_text())
        samples: list[GestureSample] = [
            [GesturePoint(x=pt["x"], y=pt["y"], t=pt["t"]) for pt in sample]
            for sample in data["samples"]
        ]
        return Gesture(
            name=data["name"],
            created_at=data["created_at"],
            samples=samples,
            action=data.get("action"),
        )
