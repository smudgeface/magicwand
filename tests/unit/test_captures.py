"""Unit tests for magicwand.captures.CaptureStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from magicwand.captures import CaptureStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_points(n: int = 20) -> list[dict]:
    return [{"x": 0.1 * i, "y": 0.2 * i, "t": i * 0.03} for i in range(n)]


_MATCH_HIT = {
    "matched": True,
    "gesture_name": "lumos",
    "confidence": 0.85,
    "distance": 0.4,
}

_MATCH_MISS = {
    "matched": False,
    "gesture_name": None,
    "confidence": 0.0,
    "distance": 3.5,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_and_list(tmp_path: Path) -> None:
    """add() then list() returns newest-first with correct summary fields."""
    store = CaptureStore(tmp_path)

    id1 = store.add(_raw_points(10), _MATCH_HIT, trimmed_count=2)
    id2 = store.add(_raw_points(15), _MATCH_MISS, trimmed_count=0)
    id3 = store.add(_raw_points(20), _MATCH_HIT, trimmed_count=5)

    captures = store.list()

    assert len(captures) == 3
    # Newest first: id3, id2, id1
    assert captures[0]["id"] == id3
    assert captures[1]["id"] == id2
    assert captures[2]["id"] == id1

    # Spot-check fields on the first result
    first = captures[0]
    assert "id" in first
    assert "timestamp" in first
    assert "point_count" in first
    assert "duration_s" in first
    assert "match_result" in first
    assert "trimmed_points" in first
    # raw_points should NOT be in the summary
    assert "raw_points" not in first

    assert first["point_count"] == 20
    assert first["trimmed_points"] == 5
    assert first["match_result"]["matched"] is True
    assert first["match_result"]["gesture_name"] == "lumos"


def test_ring_buffer_evicts(tmp_path: Path) -> None:
    """With max_captures=5, adding 7 retains only the 5 newest."""
    store = CaptureStore(tmp_path, max_captures=5)

    ids = [store.add(_raw_points(), _MATCH_MISS, trimmed_count=0) for _ in range(7)]

    captures = store.list(limit=100)
    assert len(captures) == 5

    # The retained ids should be the 5 newest (ids[2] through ids[6])
    retained_ids = {c["id"] for c in captures}
    assert ids[0] not in retained_ids
    assert ids[1] not in retained_ids
    for i in range(2, 7):
        assert ids[i] in retained_ids


def test_get_by_id(tmp_path: Path) -> None:
    """get() returns the capture including raw_points."""
    store = CaptureStore(tmp_path)
    pts = _raw_points(12)
    capture_id = store.add(pts, _MATCH_HIT, trimmed_count=1)

    result = store.get(capture_id)

    assert result is not None
    assert result["id"] == capture_id
    assert "raw_points" in result
    assert len(result["raw_points"]) == 12
    assert result["match_result"]["gesture_name"] == "lumos"


def test_get_nonexistent(tmp_path: Path) -> None:
    """get() returns None for an id that doesn't exist."""
    store = CaptureStore(tmp_path)
    assert store.get(999) is None


def test_clear(tmp_path: Path) -> None:
    """clear() removes all captures; list() returns empty."""
    store = CaptureStore(tmp_path)
    store.add(_raw_points(), _MATCH_HIT, trimmed_count=0)
    store.add(_raw_points(), _MATCH_MISS, trimmed_count=0)
    store.add(_raw_points(), _MATCH_HIT, trimmed_count=0)

    count = store.clear()

    assert count == 3
    assert store.list() == []


def test_set_max_evicts(tmp_path: Path) -> None:
    """set_max() trims captures that exceed the new limit."""
    store = CaptureStore(tmp_path)

    ids = [store.add(_raw_points(), _MATCH_MISS, trimmed_count=0) for _ in range(10)]

    store.set_max(3)

    captures = store.list(limit=100)
    assert len(captures) == 3

    # The newest 3 should be retained
    retained_ids = {c["id"] for c in captures}
    for i in range(7):
        assert ids[i] not in retained_ids
    for i in range(7, 10):
        assert ids[i] in retained_ids


def test_persistence(tmp_path: Path) -> None:
    """Captures survive across CaptureStore instances (JSONL on disk)."""
    store1 = CaptureStore(tmp_path)
    id1 = store1.add(_raw_points(5), _MATCH_HIT, trimmed_count=0)
    id2 = store1.add(_raw_points(10), _MATCH_MISS, trimmed_count=2)
    del store1

    store2 = CaptureStore(tmp_path)
    captures = store2.list(limit=100)

    assert len(captures) == 2
    ids = {c["id"] for c in captures}
    assert id1 in ids
    assert id2 in ids

    # Verify content survived serialization
    loaded = store2.get(id2)
    assert loaded is not None
    assert loaded["match_result"]["matched"] is False
    assert loaded["trimmed_points"] == 2


def test_matched_only_filter(tmp_path: Path) -> None:
    """list(matched_only=True) returns only successful matches."""
    store = CaptureStore(tmp_path)

    store.add(_raw_points(), _MATCH_HIT, trimmed_count=0)
    store.add(_raw_points(), _MATCH_MISS, trimmed_count=0)
    store.add(_raw_points(), _MATCH_HIT, trimmed_count=1)
    store.add(_raw_points(), _MATCH_MISS, trimmed_count=0)

    matched = store.list(matched_only=True)
    assert len(matched) == 2
    assert all(c["match_result"]["matched"] is True for c in matched)
