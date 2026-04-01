"""Tests for the optional clippy_native Rust extension module.

These tests are skipped entirely if the native module is not installed.
They validate that native implementations produce identical output to the
pure-Python fallbacks.
"""
from __future__ import annotations

import json
import random

import pytest

clippy_native = pytest.importorskip("clippy_native")

from clippy.noise import _noise3_python  # noqa: E402
from clippy.types import Cell, OutputCells, OutputPixels, Pixel  # noqa: E402


class TestNativeVersion:
    def test_returns_string(self) -> None:
        assert isinstance(clippy_native.native_version(), str)


class TestSerializeCellsParity:
    """Compare native serialize_cells against Python OutputCells.to_json."""

    def _python_to_json(self, cells: list[Cell]) -> str:
        import os
        old = os.environ.get("CLIPPY_FORCE_PYTHON")
        os.environ["CLIPPY_FORCE_PYTHON"] = "1"
        try:
            # Reimport to pick up the force flag — but the flag is checked
            # at import time, so we need to use the Python path directly.
            # Instead, just call the Python serialization logic inline.
            from clippy.types import _color_cache, _CHAR_TABLE
            parts: list[str] = []
            cc = _color_cache
            ct = _CHAR_TABLE
            for c in cells:
                o = ord(c.character)
                ch = ct[o] if o < 128 else c.character
                fg_color = c.fg
                if fg_color is not None:
                    fg = cc.get(fg_color)
                    if fg is None:
                        fg = f"[{fg_color[0]}, {fg_color[1]}, {fg_color[2]}, {fg_color[3]}]"
                        cc[fg_color] = fg
                else:
                    fg = "null"
                bg_color = c.bg
                if bg_color is not None:
                    bg = cc.get(bg_color)
                    if bg is None:
                        bg = f"[{bg_color[0]}, {bg_color[1]}, {bg_color[2]}, {bg_color[3]}]"
                        cc[bg_color] = bg
                else:
                    bg = "null"
                parts.append(
                    f'{{"character": "{ch}", '
                    f'"coordinates": [{c.coordinates[0]}, {c.coordinates[1]}], '
                    f'"fg": {fg}, "bg": {bg}}}'
                )
            return '{"output_cells": [' + ", ".join(parts) + "]}"
        finally:
            if old is None:
                os.environ.pop("CLIPPY_FORCE_PYTHON", None)
            else:
                os.environ["CLIPPY_FORCE_PYTHON"] = old

    def test_empty_list(self) -> None:
        result = clippy_native.serialize_cells([])
        assert json.loads(result) == {"output_cells": []}

    def test_basic_cell(self) -> None:
        cell = Cell("X", (5, 3), (1.0, 0.0, 0.0, 1.0), None)
        native = clippy_native.serialize_cells([cell])
        parsed = json.loads(native)
        assert parsed["output_cells"][0]["character"] == "X"
        assert parsed["output_cells"][0]["coordinates"] == [5, 3]
        assert parsed["output_cells"][0]["fg"] == [1.0, 0.0, 0.0, 1.0]
        assert parsed["output_cells"][0]["bg"] is None

    def test_special_chars(self) -> None:
        for ch in ['"', '\\', '\n', '\r', '\t', '\x00', '\x1f']:
            cell = Cell(ch, (0, 0), (1.0, 1.0, 1.0, 1.0), None)
            native = clippy_native.serialize_cells([cell])
            parsed = json.loads(native)
            assert parsed["output_cells"][0]["character"] == ch

    def test_unicode(self) -> None:
        for ch in ['▀', '▄', '█', '▓', '░', '🔥', '日']:
            cell = Cell(ch, (0, 0), (1.0, 1.0, 1.0, 1.0), None)
            native = clippy_native.serialize_cells([cell])
            parsed = json.loads(native)
            assert parsed["output_cells"][0]["character"] == ch

    def test_both_colors_null(self) -> None:
        cell = Cell("A", (0, 0), None, None)
        native = clippy_native.serialize_cells([cell])
        parsed = json.loads(native)
        assert parsed["output_cells"][0]["fg"] is None
        assert parsed["output_cells"][0]["bg"] is None

    def test_both_colors_present(self) -> None:
        cell = Cell("A", (0, 0), (1.0, 0.5, 0.0, 1.0), (0.0, 0.0, 0.0, 0.5))
        native = clippy_native.serialize_cells([cell])
        parsed = json.loads(native)
        assert parsed["output_cells"][0]["fg"] == [1.0, 0.5, 0.0, 1.0]
        assert parsed["output_cells"][0]["bg"] == [0.0, 0.0, 0.0, 0.5]

    def test_parity_with_python(self) -> None:
        """JSON-semantic equality between native and Python for all 128 ASCII chars."""
        cells = [
            Cell(chr(i), (i, i % 24), (0.5, 0.5, 0.5, 1.0), None)
            for i in range(128)
        ]
        native = clippy_native.serialize_cells(cells)
        python = self._python_to_json(cells)
        assert json.loads(native) == json.loads(python)


class TestSerializePixelsParity:
    def test_empty_list(self) -> None:
        result = clippy_native.serialize_pixels([])
        assert json.loads(result) == {"output_pixels": []}

    def test_basic_pixel(self) -> None:
        pixel = Pixel((10, 20), (0.0, 1.0, 0.0, 1.0))
        native = clippy_native.serialize_pixels([pixel])
        parsed = json.loads(native)
        assert parsed["output_pixels"][0]["coordinates"] == [10, 20]
        assert parsed["output_pixels"][0]["color"] == [0.0, 1.0, 0.0, 1.0]

    def test_null_color(self) -> None:
        pixel = Pixel((0, 0), None)
        native = clippy_native.serialize_pixels([pixel])
        parsed = json.loads(native)
        assert parsed["output_pixels"][0]["color"] is None

    def test_parity_with_python(self) -> None:
        pixels = [Pixel((x, y), (x / 80.0, y / 48.0, 0.5, 1.0))
                  for x in range(80) for y in range(48)]
        native_json = clippy_native.serialize_pixels(pixels)
        python_json = OutputPixels(pixels).to_json()
        # The Python path may use native too — compare at JSON level
        assert json.loads(native_json) == json.loads(python_json)


class TestTintColor:
    def test_basic(self) -> None:
        result = clippy_native.tint_color((1.0, 0.5, 0.25, 0.8), 0.5)
        assert result == pytest.approx((0.5, 0.25, 0.125, 0.8))

    def test_preserves_alpha(self) -> None:
        result = clippy_native.tint_color((1.0, 1.0, 1.0, 0.3), 0.0)
        assert result[3] == pytest.approx(0.3)

    def test_identity(self) -> None:
        color = (0.1, 0.2, 0.3, 0.4)
        assert clippy_native.tint_color(color, 1.0) == pytest.approx(color)


class TestFadeColor:
    def test_basic(self) -> None:
        result = clippy_native.fade_color((1.0, 0.5, 0.25, 0.8), 0.5)
        assert result == pytest.approx((1.0, 0.5, 0.25, 0.4))

    def test_preserves_rgb(self) -> None:
        result = clippy_native.fade_color((0.1, 0.2, 0.3, 1.0), 0.5)
        assert result[:3] == pytest.approx((0.1, 0.2, 0.3))

    def test_identity(self) -> None:
        color = (0.1, 0.2, 0.3, 0.4)
        assert clippy_native.fade_color(color, 1.0) == pytest.approx(color)


class TestNoise3Parity:
    """Verify native noise3 matches the pure-Python implementation."""

    def test_known_values(self) -> None:
        """Spot-check a few known inputs."""
        for x, y, z in [(0.0, 0.0, 0.0), (1.5, 2.3, 0.7), (-1.0, -2.0, 3.0)]:
            native = clippy_native.noise3(x, y, z)
            python = _noise3_python(x, y, z)
            assert native == pytest.approx(python, abs=1e-10), \
                f"Mismatch at ({x}, {y}, {z}): native={native}, python={python}"

    def test_grid_parity(self) -> None:
        """Compare over a grid of inputs."""
        for ix in range(-5, 6):
            for iy in range(-5, 6):
                for iz in range(-5, 6):
                    x, y, z = ix * 0.37, iy * 0.37, iz * 0.37
                    native = clippy_native.noise3(x, y, z)
                    python = _noise3_python(x, y, z)
                    assert native == pytest.approx(python, abs=1e-10), \
                        f"Mismatch at ({x}, {y}, {z})"

    def test_range(self) -> None:
        """All outputs should be in [-1, 1]."""
        rng = random.Random(42)
        for _ in range(1000):
            x = rng.uniform(-100, 100)
            y = rng.uniform(-100, 100)
            z = rng.uniform(-100, 100)
            val = clippy_native.noise3(x, y, z)
            assert -1.0 <= val <= 1.0


class TestComputeHeatParity:
    """Verify native compute_heat produces equivalent results."""

    def test_empty_burning(self) -> None:
        w, h = 10, 10
        heat_flat = [0.0] * (w * h)
        is_hot_flat = [False] * (w * h)
        heat_out, is_hot_out, hot_list, shimmer = clippy_native.compute_heat(
            heat_flat, is_hot_flat,
            [],  # old_hot_list
            [],  # burning_positions
            [0] * (w * h),  # ignition_tick
            [0] * (w * h),  # cell_state
            100,  # tick_count
            w, h,
            60,  # burn_duration
            0.18,  # heat_decay_max
            [], [],  # drift_vals, decay_vals
            0, 0, 0, 0,  # bounding box
        )
        assert hot_list == []
        assert shimmer == []

    def test_single_burning_cell(self) -> None:
        w, h = 20, 20
        heat_flat = [0.0] * (w * h)
        is_hot_flat = [False] * (w * h)
        ignition_flat = [0] * (w * h)
        state_flat = [0] * (w * h)  # CLEAR = 0

        # Place a burning cell at (10, 15), ignited at tick 90
        bx, by = 10, 15
        ignition_flat[by * w + bx] = 90

        burning = [(bx, by)]

        # Pre-generate randoms
        rng = random.Random(100)
        n_randoms = 200  # generous
        drift_vals = [rng.randint(-1, 1) for _ in range(n_randoms)]
        decay_vals = [rng.random() * 0.18 for _ in range(n_randoms)]

        heat_out, is_hot_out, hot_list, shimmer = clippy_native.compute_heat(
            heat_flat, is_hot_flat,
            [],  # old_hot_list
            burning,
            ignition_flat, state_flat,
            100,  # tick_count (age = 10, ratio = 10/60 < 0.3 → heat = 1.0)
            w, h,
            60, 0.18,
            drift_vals, decay_vals,
            bx, bx, by, by,
        )

        # The burning cell itself should be hot with heat 1.0
        assert heat_out[by * w + bx] == 1.0
        assert is_hot_out[by * w + bx] is True
        assert (bx, by) in hot_list
        # There should be propagated heat above the burning cell
        assert len(hot_list) > 1
