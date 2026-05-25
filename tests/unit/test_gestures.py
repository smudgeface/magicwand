"""Unit tests for magicwand.gestures — GestureStore, GesturePoint, validate_gesture_name."""

from __future__ import annotations

import pytest
from pathlib import Path

from magicwand.gestures import GestureStore, GesturePoint, validate_gesture_name


# ---------------------------------------------------------------------------
# GestureStore — create / get / delete
# ---------------------------------------------------------------------------

def test_create_gesture(tmp_path: Path) -> None:
    """create() writes a JSON file to the gestures directory."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    assert (tmp_path / "lumos.json").exists()


def test_create_duplicate_raises(tmp_path: Path) -> None:
    """Creating the same gesture name twice raises ValueError."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    with pytest.raises(ValueError):
        store.create("lumos")


def test_delete_gesture(tmp_path: Path) -> None:
    """delete() removes the JSON file and makes get() return None."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    assert store.delete("lumos") is True
    assert not (tmp_path / "lumos.json").exists()
    assert store.get("lumos") is None


def test_delete_nonexistent(tmp_path: Path) -> None:
    """Deleting an unknown gesture name returns False."""
    store = GestureStore(tmp_path)
    assert store.delete("nox") is False


# ---------------------------------------------------------------------------
# GestureStore — samples
# ---------------------------------------------------------------------------

def test_add_sample(tmp_path: Path) -> None:
    """add_sample() stores a sample; get() shows 1 sample with the correct point count."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    sample = [GesturePoint(x=i * 0.1, y=i * 0.1, t=float(i)) for i in range(5)]
    store.add_sample("lumos", sample)
    gesture = store.get("lumos")
    assert gesture is not None
    assert len(gesture.samples) == 1
    assert len(gesture.samples[0]) == 5


def test_remove_sample(tmp_path: Path) -> None:
    """remove_sample() on index 0 leaves 1 sample when 2 were added."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    sample_a = [GesturePoint(x=0.1, y=0.1, t=0.0)]
    sample_b = [GesturePoint(x=0.2, y=0.2, t=0.1)]
    store.add_sample("lumos", sample_a)
    store.add_sample("lumos", sample_b)
    assert store.remove_sample("lumos", 0) is True
    gesture = store.get("lumos")
    assert gesture is not None
    assert len(gesture.samples) == 1


def test_remove_sample_invalid_index(tmp_path: Path) -> None:
    """remove_sample() with an out-of-range index returns False."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    store.add_sample("lumos", [GesturePoint(x=0.5, y=0.5, t=0.0)])
    assert store.remove_sample("lumos", 99) is False


# ---------------------------------------------------------------------------
# GestureStore — list
# ---------------------------------------------------------------------------

def test_list_gestures(tmp_path: Path) -> None:
    """list() returns gesture names sorted alphabetically."""
    store = GestureStore(tmp_path)
    store.create("c-spell")
    store.create("a-spell")
    store.create("b-spell")
    assert store.list() == ["a-spell", "b-spell", "c-spell"]


# ---------------------------------------------------------------------------
# validate_gesture_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["lumos", "expecto-patronum", "a1", "x"])
def test_name_validation_valid(name: str) -> None:
    """Valid names pass validation."""
    assert validate_gesture_name(name) is True


@pytest.mark.parametrize("name", [
    "Lumos",       # uppercase not allowed
    "123abc",      # must start with a letter
    "a_b",         # underscore not allowed
    "",            # empty string
    "a" * 31,      # too long (max 30 chars: 1 leading + up to 29 more)
    "-start",      # must start with a letter
])
def test_name_validation_invalid(name: str) -> None:
    """Invalid names fail validation."""
    assert validate_gesture_name(name) is False


# ---------------------------------------------------------------------------
# GestureStore — persistence across reload
# ---------------------------------------------------------------------------

def test_gesture_persists_on_reload(tmp_path: Path) -> None:
    """Data written by one GestureStore instance is loaded by a fresh instance."""
    store = GestureStore(tmp_path)
    store.create("lumos")
    sample = [GesturePoint(x=0.1 * i, y=0.2 * i, t=float(i)) for i in range(5)]
    store.add_sample("lumos", sample)

    # Create a brand-new store pointing at the same directory.
    store2 = GestureStore(tmp_path)
    gesture = store2.get("lumos")
    assert gesture is not None
    assert len(gesture.samples) == 1
    assert len(gesture.samples[0]) == 5
