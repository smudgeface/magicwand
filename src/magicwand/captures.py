"""Capture history — ring buffer of completed gesture attempts.

Stores raw points and match results for every gesture attempt, persisted
to a JSONL file on disk. Thread-safe for concurrent access from the
camera thread.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class CaptureStore:
    """Ring buffer of gesture captures on disk.

    Each capture records the raw points, match outcome, and metadata.
    Oldest entries are evicted when the buffer exceeds *max_captures*.
    """

    def __init__(self, captures_dir: Path, max_captures: int = 200) -> None:
        self._dir = captures_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max = max_captures
        self._lock = threading.Lock()
        self._captures: list[dict] = []
        self._next_id: int = 1
        self._history_path = self._dir / "history.jsonl"
        self._load()

    # -- Public API ----------------------------------------------------------

    def add(self, raw_points: list, match_result, trimmed_count: int) -> int:
        """Add a capture. Returns its ID. Evicts oldest if over max.

        *raw_points* is a list of GesturePoint (or dicts with x, y, t).
        *match_result* is a MatchResult dataclass or compatible object.
        """
        # Serialize points
        serialized_points = []
        for pt in raw_points:
            if hasattr(pt, "x"):
                serialized_points.append({"x": pt.x, "y": pt.y, "t": pt.t})
            else:
                serialized_points.append(pt)

        # Serialize match result
        if hasattr(match_result, "matched"):
            mr = {
                "matched": match_result.matched,
                "gesture_name": match_result.gesture_name,
                "confidence": match_result.confidence,
                "distance": match_result.distance,
            }
        else:
            mr = match_result

        # Compute duration
        if serialized_points:
            duration_s = serialized_points[-1]["t"] - serialized_points[0]["t"]
        else:
            duration_s = 0.0

        with self._lock:
            capture_id = self._next_id
            self._next_id += 1

            capture = {
                "id": capture_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_points": serialized_points,
                "point_count": len(serialized_points),
                "duration_s": round(duration_s, 4),
                "match_result": mr,
                "trimmed_points": trimmed_count,
            }

            self._captures.append(capture)

            # Evict oldest if over max
            if len(self._captures) > self._max:
                self._captures = self._captures[-self._max :]

            self._persist()

        return capture_id

    def list(
        self, limit: int = 50, offset: int = 0, matched_only: bool = False
    ) -> list[dict]:
        """List recent captures (newest first), with pagination.

        Returns summary dicts (without raw_points).
        """
        with self._lock:
            # Newest first
            ordered = list(reversed(self._captures))

        if matched_only:
            ordered = [
                c for c in ordered if c["match_result"].get("matched", False)
            ]

        page = ordered[offset : offset + limit]

        # Return summaries (omit raw_points)
        summaries = []
        for c in page:
            summaries.append(
                {
                    "id": c["id"],
                    "timestamp": c["timestamp"],
                    "point_count": c["point_count"],
                    "duration_s": c["duration_s"],
                    "match_result": c["match_result"],
                    "trimmed_points": c["trimmed_points"],
                }
            )
        return summaries

    def get(self, capture_id: int) -> dict | None:
        """Get a single capture by ID, including raw_points."""
        with self._lock:
            for c in self._captures:
                if c["id"] == capture_id:
                    return dict(c)
        return None

    def clear(self) -> int:
        """Clear all captures. Returns count deleted."""
        with self._lock:
            count = len(self._captures)
            self._captures = []
            self._persist()
        return count

    def set_max(self, max_captures: int) -> None:
        """Update retention limit. Evicts if current count exceeds new max."""
        with self._lock:
            self._max = max_captures
            if len(self._captures) > self._max:
                self._captures = self._captures[-self._max :]
                self._persist()

    # -- Internal helpers ----------------------------------------------------

    def _persist(self) -> None:
        """Write all captures to history.jsonl (overwrite entire file).

        Must be called while holding self._lock.
        """
        with self._history_path.open("w") as f:
            for capture in self._captures:
                f.write(json.dumps(capture) + "\n")

    def _load(self) -> None:
        """Read history.jsonl on startup, populating internal state."""
        if not self._history_path.exists():
            return

        captures: list[dict] = []
        try:
            with self._history_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        captures.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            # Corrupted file — start fresh
            return

        # Only keep up to max
        if len(captures) > self._max:
            captures = captures[-self._max :]

        self._captures = captures

        # Set next_id based on existing data
        if self._captures:
            max_id = max(c["id"] for c in self._captures)
            self._next_id = max_id + 1
