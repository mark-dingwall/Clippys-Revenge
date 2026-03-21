"""Tests for clippy.types — wire format correctness."""
import json
import os
from pathlib import Path

import pytest

from clippy.types import (
    Cell,
    CursorShakeDetector,
    Pixel,
    PTYUpdate,
    TTYResize,
    OutputText,
    OutputCells,
    OutputPixels,
    from_json,
)

GOLDEN_DIR = Path(__file__).parent / "golden"


# --- Golden file validation ---

GOLDEN_OUTPUT_CASES = [
    (
        "output_text_basic.json",
        OutputText(
            text="\U0001f525",
            coordinates=(40, 12),
            fg=(1.0, 0.5, 0.0, 1.0),
            bg=None,
        ),
    ),
    (
        "output_text_null_bg.json",
        OutputText(
            text="It looks like you're writing a letter!",
            coordinates=(0, 0),
            fg=(1.0, 1.0, 0.0, 1.0),
            bg=None,
        ),
    ),
    (
        "output_cells_empty.json",
        OutputCells(cells=[]),
    ),
    (
        "output_cells_unicode.json",
        OutputCells(cells=[
            Cell(character="\u2584", coordinates=(20, 10),
                 fg=(1.0, 0.3, 0.0, 1.0), bg=None),
        ]),
    ),
    (
        "output_pixels_single.json",
        OutputPixels(pixels=[
            Pixel(coordinates=(79, 47), color=(0.0, 1.0, 0.0, 1.0)),
        ]),
    ),
    (
        "output_pixels_zero_alpha.json",
        OutputPixels(pixels=[
            Pixel(coordinates=(0, 0), color=(1.0, 0.0, 0.0, 0.0)),
        ]),
    ),
    (
        "output_pixels_null_color.json",
        OutputPixels(pixels=[
            Pixel(coordinates=(5, 10), color=None),
        ]),
    ),
]


@pytest.mark.parametrize(
    "filename,obj",
    GOLDEN_OUTPUT_CASES,
    ids=[c[0] for c in GOLDEN_OUTPUT_CASES],
)
def test_golden_output(filename, obj):
    """Serialize output object and compare against golden file."""
    golden_path = GOLDEN_DIR / filename
    actual = obj.to_json()
    if os.environ.get("UPDATE_GOLDEN"):
        golden_path.write_text(actual)
    expected = json.loads(golden_path.read_text())
    assert json.loads(actual) == expected


def test_golden_pty_update():
    """Parse golden pty_update JSON and verify Python object."""
    raw = (GOLDEN_DIR / "pty_update_basic.json").read_text()
    msg = from_json(raw)
    assert isinstance(msg, PTYUpdate)
    assert msg.size == (80, 24)
    assert len(msg.cells) == 1
    assert msg.cells[0].character == "H"
    assert msg.cells[0].coordinates == (0, 0)
    assert msg.cells[0].fg == (1.0, 1.0, 1.0, 1.0)
    assert msg.cells[0].bg == (0.0, 0.0, 0.0, 1.0)
    assert msg.cursor == (0, 0)


def test_golden_tty_resize():
    """Parse golden tty_resize JSON and verify Python object."""
    raw = (GOLDEN_DIR / "tty_resize.json").read_text()
    msg = from_json(raw)
    assert isinstance(msg, TTYResize)
    assert msg.width == 120
    assert msg.height == 40


# --- Round-trip tests ---

def test_output_text_roundtrip():
    obj = OutputText(text="hello", coordinates=(10, 5),
                     fg=(0.0, 1.0, 0.0, 1.0), bg=None)
    data = json.loads(obj.to_json())
    assert "output_text" in data
    inner = data["output_text"]
    assert inner["text"] == "hello"
    assert inner["coordinates"] == [10, 5]
    assert inner["fg"] == [0.0, 1.0, 0.0, 1.0]
    assert inner["bg"] is None


def test_output_cells_roundtrip():
    cell = Cell(character="X", coordinates=(5, 3),
                fg=(1.0, 0.0, 0.0, 1.0), bg=None)
    obj = OutputCells(cells=[cell])
    data = json.loads(obj.to_json())
    assert "output_cells" in data
    # Direct array format — no "cells" wrapper
    cells = data["output_cells"]
    assert isinstance(cells, list)
    assert len(cells) == 1
    assert cells[0]["character"] == "X"
    assert cells[0]["coordinates"] == [5, 3]
    assert cells[0]["fg"] == [1.0, 0.0, 0.0, 1.0]
    assert cells[0]["bg"] is None


def test_output_pixels_roundtrip():
    pixel = Pixel(coordinates=(79, 47), color=(0.0, 1.0, 0.0, 1.0))
    obj = OutputPixels(pixels=[pixel])
    data = json.loads(obj.to_json())
    assert "output_pixels" in data
    # Direct array format — no "pixels" wrapper
    pixels = data["output_pixels"]
    assert isinstance(pixels, list)
    assert len(pixels) == 1
    assert pixels[0]["coordinates"] == [79, 47]
    assert pixels[0]["color"] == [0.0, 1.0, 0.0, 1.0]


# --- Input deserialization ---

def test_parse_pty_update(sample_pty_update_json):
    msg = from_json(sample_pty_update_json)
    assert isinstance(msg, PTYUpdate)
    assert msg.size == (80, 24)
    assert len(msg.cells) == 1
    assert msg.cells[0].character == "A"
    assert msg.cursor == (0, 0)  # default when absent


def test_parse_pty_update_with_cursor():
    raw = '{"pty_update": {"size": [80, 24], "cells": [], "cursor": [10, 5]}}'
    msg = from_json(raw)
    assert isinstance(msg, PTYUpdate)
    assert msg.cursor == (10, 5)


def test_parse_tty_resize(sample_tty_resize_json):
    msg = from_json(sample_tty_resize_json)
    assert isinstance(msg, TTYResize)
    assert msg.width == 120
    assert msg.height == 40


# --- Edge cases ---

def test_empty_cells():
    raw = '{"pty_update": {"size": [80, 24], "cells": []}}'
    msg = from_json(raw)
    assert isinstance(msg, PTYUpdate)
    assert msg.cells == []


def test_null_colors():
    raw = ('{"pty_update": {"size": [80, 24], "cells": '
           '[{"character": "X", "coordinates": [0, 0], "fg": null, "bg": null}]}}')
    msg = from_json(raw)
    assert isinstance(msg, PTYUpdate)
    assert msg.cells[0].fg is None
    assert msg.cells[0].bg is None


def test_unicode_cell():
    cell = Cell(character="\u2584", coordinates=(0, 0),
                fg=(1.0, 1.0, 1.0, 1.0), bg=None)
    obj = OutputCells(cells=[cell])
    data = json.loads(obj.to_json())
    assert data["output_cells"][0]["character"] == "\u2584"


def test_zero_alpha_preserved():
    pixel = Pixel(coordinates=(0, 0), color=(1.0, 0.0, 0.0, 0.0))
    obj = OutputPixels(pixels=[pixel])
    data = json.loads(obj.to_json())
    assert data["output_pixels"][0]["color"] == [1.0, 0.0, 0.0, 0.0]


def test_pixel_optional_color():
    pixel = Pixel(coordinates=(0, 0))
    assert pixel.color is None
    obj = OutputPixels(pixels=[pixel])
    data = json.loads(obj.to_json())
    assert data["output_pixels"][0]["color"] is None


def test_output_text_with_both_colors():
    obj = OutputText(
        text="hi",
        coordinates=(1, 2),
        fg=(1.0, 0.0, 0.0, 1.0),
        bg=(0.0, 0.0, 1.0, 0.5),
    )
    data = json.loads(obj.to_json())
    inner = data["output_text"]
    assert inner["fg"] == [1.0, 0.0, 0.0, 1.0]
    assert inner["bg"] == [0.0, 0.0, 1.0, 0.5]


# --- Malformed input ---

@pytest.mark.parametrize("raw", [
    "",                         # empty
    "   ",                      # whitespace
    "not json at all",          # invalid JSON
    "{unclosed",                # truncated JSON
    "null",                     # valid JSON, not a dict
    "42",                       # JSON number
    '{"unknown_key": {}}',      # unknown message type
    '{"pty_update": null}',     # null payload
    # Tuple-length validation (M4)
    '{"pty_update": {"size": [80], "cells": []}}',          # size length 1
    '{"pty_update": {"size": [80, 24, 1], "cells": []}}',   # size length 3
    '{"pty_update": {"size": [80, 24], "cells": [], "cursor": [0]}}',  # cursor length 1
    '{"pty_update": {"size": [80, 24], "cells": [{"character": "A", "coordinates": [0], "fg": null, "bg": null}]}}',  # coordinates length 1
    '{"pty_update": {"size": [80, 24], "cells": [{"character": "A", "coordinates": [0, 0], "fg": [1.0, 0.0], "bg": null}]}}',  # fg length 2
    # tty_resize missing fields
    '{"tty_resize": {"width": 80}}',       # missing height
    '{"tty_resize": {"height": 24}}',      # missing width
    '{"tty_resize": {}}',                  # both missing
])
def test_malformed_input_returns_none(raw):
    assert from_json(raw) is None


# --- CursorShakeDetector ---

class TestCursorShakeDetector:
    def test_first_call_never_fires(self):
        d = CursorShakeDetector()
        assert d.update((10, 5)) is False

    def test_minimal_sequence_fires(self):
        """7 positions [0,5,0,5,0,5,0] → 5 reversals → True on 7th call."""
        d = CursorShakeDetector()
        results = []
        for x in [0, 5, 0, 5, 0, 5, 0]:
            results.append(d.update((x, 0)))
        assert results[-1] is True

    def test_constant_x_never_fires(self):
        d = CursorShakeDetector()
        for _ in range(100):
            assert d.update((20, 0)) is False

    def test_vertical_only_never_fires(self):
        d = CursorShakeDetector()
        for y in range(100):
            assert d.update((10, y)) is False

    def test_monotonic_rightward_never_fires(self):
        """Simulates typing — cursor moves only rightward."""
        d = CursorShakeDetector()
        for x in range(80):
            assert d.update((x, 0)) is False

    def test_reusable_after_trigger(self):
        d = CursorShakeDetector()
        # First shake
        for x in [0, 5, 0, 5, 0, 5, 0]:
            d.update((x, 0))
        # Internal state should have been cleared
        assert d._reversal_ticks == []
        # Second shake should also fire
        results = []
        for x in [10, 30, 10, 30, 10, 30, 10]:
            results.append(d.update((x, 0)))
        assert any(r is True for r in results), "Second shake should also trigger"

    def test_state_fully_reset_after_trigger(self):
        """After shake fires, _last_x and _last_x_dir are cleared to prevent free reversals."""
        d = CursorShakeDetector()
        for x in [0, 5, 0, 5, 0, 5, 0]:
            d.update((x, 0))
        assert d._last_x is None
        assert d._last_x_dir == 0
        assert d._reversal_ticks == []

    def test_reversals_expire_after_window(self):
        """2 reversals + 61 idle ticks → pruned → 3rd alone doesn't fire."""
        d = CursorShakeDetector()
        # Build 2 reversals
        d.update((0, 0))
        d.update((10, 0))   # direction: right
        d.update((5, 0))    # reversal 1
        d.update((15, 0))   # reversal 2
        # 61 idle ticks (same position) — advances the tick counter without movement
        for _ in range(61):
            d.update((15, 0))
        # Now one more reversal — old ones should be pruned
        d.update((5, 0))    # reversal 3, but old 2 are gone
        assert d.update((15, 0)) is False  # only 1 recent reversal in window

    def test_reset_clears_state(self):
        """reset() clears all accumulated state but keeps monotonic tick counter."""
        d = CursorShakeDetector()
        # Build some state
        d.update((0, 0))
        d.update((10, 0))
        d.update((5, 0))  # reversal
        assert len(d._reversal_ticks) == 1
        assert d._last_x is not None
        assert d._last_x_dir != 0
        old_tick = d._tick

        d.reset()

        assert d._last_x is None
        assert d._last_x_dir == 0
        assert d._reversal_ticks == []
        # Tick counter is NOT reset — it's monotonic for window pruning
        assert d._tick == old_tick

    def test_reset_prevents_carryover(self):
        """After reset(), old reversals don't count toward the next gesture."""
        d = CursorShakeDetector()
        # Build 4 reversals (one short of triggering)
        d.update((0, 0))
        d.update((10, 0))
        d.update((5, 0))    # reversal 1
        d.update((15, 0))   # reversal 2
        d.update((5, 0))    # reversal 3
        d.update((15, 0))   # reversal 4
        assert len(d._reversal_ticks) == 4

        d.reset()

        # A single reversal should not trigger (would need 5 fresh ones)
        d.update((0, 0))
        d.update((10, 0))
        result = d.update((5, 0))
        assert result is False
        assert len(d._reversal_ticks) == 1

    def test_reversals_within_window_fires(self):
        """4 reversals + 50 idle ticks → still in window → 5th reversal fires."""
        d = CursorShakeDetector()
        d.update((0, 0))
        d.update((10, 0))   # direction: right
        d.update((5, 0))    # reversal 1
        d.update((15, 0))   # reversal 2
        d.update((5, 0))    # reversal 3
        d.update((15, 0))   # reversal 4
        # 50 idle ticks (within 60-tick window)
        for _ in range(50):
            d.update((15, 0))
        # 5th reversal
        result = d.update((5, 0))
        assert result is True
