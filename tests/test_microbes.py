"""Tests for clippy.effects.microbes — MicrobesEffect."""
import json

import pytest

from clippy.effects.microbes import (
    FADE_DURATION,
    SWARMING_DURATION,
    MicrobesEffect,
    Phase,
    _bresenham_line,
    _catmull_rom,
    _hsb_to_rgb,
    _thicken_point,
)
from clippy.harness import step
from clippy.types import Cell, OutputCells, PTYUpdate, TTYResize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pty_update(width=80, height=24, cursor=(0, 0)):
    return PTYUpdate(size=(width, height), cells=[], cursor=cursor)


def make_pty_json(width=80, height=24, cursor=(0, 0)):
    return json.dumps({
        "pty_update": {
            "size": [width, height],
            "cells": [],
            "cursor": list(cursor),
        }
    })


def advance(effect, ticks):
    results = []
    for _ in range(ticks):
        results.extend(effect.tick())
    return results


def run_to_phase(effect, target_phase, max_ticks=800):
    for _ in range(max_ticks):
        effect.tick()
        if effect.phase == target_phase:
            return True
    return False


# ---------------------------------------------------------------------------
# Property-based invariants (parametrized over seeds)
# ---------------------------------------------------------------------------

SEEDS = [0, 1, 42, 99, 12345]


@pytest.mark.parametrize("seed", SEEDS)
def test_coordinates_in_bounds(seed):
    """All cell coordinates must be within [0, width) x [0, height)."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(100):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"x={x} out of bounds"
                assert 0 <= y < 24, f"y={y} out of bounds (height=24)"


@pytest.mark.parametrize("seed", SEEDS)
def test_colors_in_range(seed):
    """All RGBA components must be in [0.0, 1.0]."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(100):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                for color in (cell.fg, cell.bg):
                    if color is not None:
                        for i, component in enumerate(color):
                            assert 0.0 <= component <= 1.0, (
                                f"Color component {i}={component} out of range "
                                f"at ({cell.coordinates})"
                            )


@pytest.mark.parametrize("seed", SEEDS)
def test_output_type(seed):
    """tick() returns list containing only OutputCells."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(50):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)


@pytest.mark.parametrize("seed", SEEDS)
def test_liveness(seed):
    """At least one non-empty frame in first 10 ticks after PTYUpdate."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    found_output = False
    for _ in range(10):
        outputs = effect.tick()
        if outputs:
            found_output = True
            break
    assert found_output, "No output in first 10 ticks"


@pytest.mark.parametrize("seed", SEEDS)
def test_eventual_completion(seed):
    """Effect reaches DONE within bounded ticks."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    max_ticks = SWARMING_DURATION + FADE_DURATION + 50
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=max_ticks)
    assert reached_done, f"Effect did not reach DONE in {max_ticks} ticks, stuck at {effect.phase.name}"


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

def test_idle_returns_empty():
    """tick() returns [] before any PTYUpdate."""
    effect = MicrobesEffect(seed=0, idle_secs=0)
    assert effect.tick() == []
    assert effect.phase == Phase.IDLE


def test_swarming_on_first_update():
    """Phase transitions to SWARMING after first PTYUpdate + tick."""
    effect = MicrobesEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # idle_secs=0: first tick starts effect
    assert effect.phase == Phase.SWARMING
    outputs = effect.tick()
    assert len(outputs) > 0


def test_phases_progress():
    """Phase only moves forward (monotonically increasing)."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    effect.tick()  # start effect
    prev_phase = effect.phase
    max_ticks = SWARMING_DURATION + FADE_DURATION + 50
    for _ in range(max_ticks):
        effect.tick()
        current = effect.phase
        assert current >= prev_phase, (
            f"Phase regressed from {Phase(prev_phase).name} to {Phase(current).name}"
        )
        prev_phase = current
        if current == Phase.DONE:
            break
    assert effect.phase == Phase.DONE


def test_done_returns_empty():
    """tick() returns [] after full lifecycle."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    max_ticks = SWARMING_DURATION + FADE_DURATION + 50
    assert run_to_phase(effect, Phase.DONE, max_ticks=max_ticks)
    assert effect.tick() == []
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def test_resize_no_oob():
    """No out-of-bounds coordinates after resize."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    advance(effect, 20)

    effect.on_resize(TTYResize(width=20, height=6))
    for _ in range(20):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 6, f"y={y} OOB after resize (height=6)"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_seeded_deterministic():
    """Same seed produces identical first 5 frames."""
    def collect_frames(seed):
        effect = MicrobesEffect(seed=seed, idle_secs=0)
        effect.on_pty_update(make_pty_update(40, 12))
        frames = []
        for _ in range(5):
            outputs = effect.tick()
            frame_data = []
            for out in outputs:
                for cell in out.cells:
                    frame_data.append((cell.coordinates, cell.character, cell.fg, cell.bg))
            frames.append(frame_data)
        return frames

    frames_a = collect_frames(42)
    frames_b = collect_frames(42)
    assert frames_a == frames_b


# ---------------------------------------------------------------------------
# Integration with harness.step()
# ---------------------------------------------------------------------------

def test_step_integration():
    """Use harness.step() to drive effect through a few ticks."""
    effect = MicrobesEffect(seed=0, idle_secs=0)

    # First step: PTYUpdate sets idle_until; tick starts effect but returns []
    step(effect, [make_pty_json(40, 12)])

    result = step(effect, [])
    assert len(result) >= 1
    data = json.loads(result[0])
    assert "output_cells" in data
    cells = data["output_cells"]
    assert isinstance(cells, list)
    assert len(cells) > 0

    for _ in range(5):
        result = step(effect, [])
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

def test_hsb_to_rgb():
    """Known HSB to RGB conversions."""
    # Red: H=0, S=1, B=1
    r, g, b = _hsb_to_rgb(0, 1.0, 1.0)
    assert abs(r - 1.0) < 1e-9
    assert abs(g - 0.0) < 1e-9
    assert abs(b - 0.0) < 1e-9

    # Green: H=120, S=1, B=1
    r, g, b = _hsb_to_rgb(120, 1.0, 1.0)
    assert abs(r - 0.0) < 1e-9
    assert abs(g - 1.0) < 1e-9
    assert abs(b - 0.0) < 1e-9

    # Blue: H=240, S=1, B=1
    r, g, b = _hsb_to_rgb(240, 1.0, 1.0)
    assert abs(r - 0.0) < 1e-9
    assert abs(g - 0.0) < 1e-9
    assert abs(b - 1.0) < 1e-9

    # White: H=0, S=0, B=1
    r, g, b = _hsb_to_rgb(0, 0.0, 1.0)
    assert abs(r - 1.0) < 1e-9
    assert abs(g - 1.0) < 1e-9
    assert abs(b - 1.0) < 1e-9

    # Black: H=0, S=0, B=0
    r, g, b = _hsb_to_rgb(0, 0.0, 0.0)
    assert abs(r - 0.0) < 1e-9
    assert abs(g - 0.0) < 1e-9
    assert abs(b - 0.0) < 1e-9


def test_catmull_rom():
    """Catmull-Rom interpolation endpoints."""
    # At t=0, result should be p1
    assert abs(_catmull_rom(0, 10, 20, 30, 0.0) - 10.0) < 1e-9
    # At t=1, result should be p2
    assert abs(_catmull_rom(0, 10, 20, 30, 1.0) - 20.0) < 1e-9
    # Midpoint with uniform spacing should be 15
    assert abs(_catmull_rom(0, 10, 20, 30, 0.5) - 15.0) < 1e-9


def test_bresenham_line_basic():
    """Bresenham line: horizontal, vertical, diagonal, single point."""
    # Single point
    assert _bresenham_line(5, 5, 5, 5) == [(5, 5)]

    # Horizontal
    pts = _bresenham_line(0, 0, 3, 0)
    assert pts == [(0, 0), (1, 0), (2, 0), (3, 0)]

    # Vertical
    pts = _bresenham_line(0, 0, 0, 3)
    assert pts == [(0, 0), (0, 1), (0, 2), (0, 3)]

    # Diagonal
    pts = _bresenham_line(0, 0, 3, 3)
    assert len(pts) == 4
    assert pts[0] == (0, 0)
    assert pts[-1] == (3, 3)

    # Reverse direction
    pts = _bresenham_line(3, 0, 0, 0)
    assert pts == [(3, 0), (2, 0), (1, 0), (0, 0)]


def test_thicken_point():
    """Thicken point: verify output sizes and contents for different widths."""
    # Width 1: single point
    pts = _thicken_point(5, 5, 1)
    assert pts == [(5, 5)]

    # Width 2: plus shape (5 pixels)
    pts = _thicken_point(5, 5, 2)
    assert len(pts) == 5
    assert (5, 5) in pts
    assert (4, 5) in pts
    assert (6, 5) in pts
    assert (5, 4) in pts
    assert (5, 6) in pts

    # Width 3: 3x3 block (9 pixels)
    pts = _thicken_point(5, 5, 3)
    assert len(pts) == 9
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            assert (5 + dx, 5 + dy) in pts

    # Width 4: diamond radius 2 (13 pixels)
    pts = _thicken_point(5, 5, 4)
    assert len(pts) == 13
    assert (5, 5) in pts
    # Corners of radius 2 should NOT be included (|dx|+|dy| > 2)
    assert (3, 3) not in pts
    assert (7, 7) not in pts


# ---------------------------------------------------------------------------
# Cursor-shake cancellation
# ---------------------------------------------------------------------------

def test_cancel_during_swarming():
    """cancel() during SWARMING transitions to FADING."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect
    assert effect.phase == Phase.SWARMING
    effect.cancel()
    assert effect.phase == Phase.FADING


def test_is_done_property():
    """is_done is True iff phase is DONE."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    assert not effect.is_done
    effect.on_pty_update(make_pty_update(40, 12))
    max_ticks = SWARMING_DURATION + FADE_DURATION + 50
    run_to_phase(effect, Phase.DONE, max_ticks=max_ticks)
    assert effect.is_done


# ---------------------------------------------------------------------------
# FADING alpha + ghost pixels
# ---------------------------------------------------------------------------

def test_fading_alpha_decreases():
    """At least one cell has color alpha < 1.0 during FADING."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.FADING, max_ticks=SWARMING_DURATION + 50)
    found_dimmed = False
    for _ in range(30):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                for color in (cell.fg, cell.bg):
                    if color is not None and color[3] < 1.0:
                        found_dimmed = True
        if found_dimmed or effect.phase == Phase.DONE:
            break
    assert found_dimmed, "No dimmed cells observed during FADING"
