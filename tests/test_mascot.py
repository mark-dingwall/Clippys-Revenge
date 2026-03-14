"""Tests for clippy.effects.mascot — MascotEffect."""
from __future__ import annotations

import json

import pytest

from clippy.effects.mascot import (
    CACKLE_FLIP_TICKS,
    DEMO_CACKLING_TICKS,
    DEMO_IMMINENT_DEEP_TICKS,
    DEMO_IMMINENT_EARLY_TICKS,
    DEMO_WATCHING_TICKS,
    EYE_PULSE_PERIOD,
    FACE_H,
    FACE_W,
    FPS,
    MARGIN,
    MascotEffect,
    Phase,
)
from clippy.harness import step
from clippy.types import OutputCells, PTYUpdate, TTYResize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pty_update(width=80, height=24):
    return PTYUpdate(size=(width, height), cells=[], cursor=(0, 0))


def make_pty_json(width=80, height=24):
    return json.dumps({
        "pty_update": {
            "size": [width, height],
            "cells": [],
            "cursor": [0, 0],
        }
    })


def advance(effect, ticks):
    """Advance effect N ticks; return flattened cells from last tick."""
    outputs = []
    for _ in range(ticks):
        outputs = effect.tick()
    return outputs


def run_to_phase(effect, target_phase, max_ticks=5000):
    for _ in range(max_ticks):
        effect.tick()
        if effect.phase == target_phase:
            return True
    return False


def cells_from_outputs(outputs):
    cells = []
    for out in outputs:
        if isinstance(out, OutputCells):
            cells.extend(out.cells)
    return cells


def char_at(outputs, pos):
    for out in outputs:
        if isinstance(out, OutputCells):
            for cell in out.cells:
                if tuple(cell.coordinates) == pos:
                    return cell.character
    return None


def alpha_at(outputs, pos):
    for out in outputs:
        if isinstance(out, OutputCells):
            for cell in out.cells:
                if tuple(cell.coordinates) == pos and cell.fg is not None:
                    return cell.fg[3]
    return None


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------

def test_no_output_before_pty_update():
    effect = MascotEffect(idle_secs=300)
    outputs = effect.tick()
    assert outputs == []


def test_output_after_pty_update():
    effect = MascotEffect(idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    outputs = effect.tick()
    assert len(outputs) == 1
    assert isinstance(outputs[0], OutputCells)
    assert len(outputs[0].cells) > 0


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("idle_secs", [0, 10, 60])
def test_phase_transitions(idle_secs):
    effect = MascotEffect(idle_secs=idle_secs)
    effect.on_pty_update(make_pty_update(80, 24))

    assert effect.phase == Phase.WATCHING

    assert run_to_phase(effect, Phase.IMMINENT_EARLY)
    assert effect.phase == Phase.IMMINENT_EARLY

    assert run_to_phase(effect, Phase.IMMINENT_DEEP)
    assert effect.phase == Phase.IMMINENT_DEEP

    assert run_to_phase(effect, Phase.CACKLING)
    assert effect.phase == Phase.CACKLING


# ---------------------------------------------------------------------------
# Coordinate bounds
# ---------------------------------------------------------------------------

SEEDS = [0, 1, 42, 99]
SIZES = [(80, 24), (40, 12), (120, 40)]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("w,h", SIZES)
def test_coordinates_in_bounds(seed, w, h):
    effect = MascotEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(w, h))
    for _ in range(250):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < w, f"x={x} out of bounds for width={w}"
                assert 0 <= y < h, f"y={y} out of bounds for height={h}"


# ---------------------------------------------------------------------------
# Color range
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_colors_in_range(seed):
    effect = MascotEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(250):
        outputs = effect.tick()
        for out in outputs:
            if isinstance(out, OutputCells):
                for cell in out.cells:
                    if cell.fg is not None:
                        for component in cell.fg:
                            assert 0.0 <= component <= 1.0, (
                                f"Color component {component} out of range in {cell.fg}"
                            )


# ---------------------------------------------------------------------------
# Blink
# ---------------------------------------------------------------------------

def test_blink_changes_eye_char():
    w, h = 80, 24
    effect = MascotEffect(idle_secs=300)  # stays in WATCHING for 6300+ ticks
    effect.on_pty_update(make_pty_update(w, h))

    corner_x = w - FACE_W - MARGIN
    corner_y = h - FACE_H - MARGIN
    eye_pos = (corner_x, corner_y + 1)  # left eye at (col, row 1)

    # Tick 10: no blink (10 % 100 = 10 >= 3)
    for _ in range(10):
        outputs = effect.tick()
    no_blink_char = char_at(outputs, eye_pos)

    # Tick 100: blink (100 % 100 = 0 < 3)
    for _ in range(90):
        effect.tick()
    blink_outputs = effect.tick()  # tick 101 (100 already at non-blink, 101 = 1 < 3)

    # More reliable: advance until we hit a blink tick
    # Blink ticks: t % BLINK_PERIOD < BLINK_DURATION, i.e., t in {0,1,2, 100,101,102, ...}
    # From tick 10, we advance to tick 100 (90 more ticks)
    blink_char = char_at(blink_outputs, eye_pos)

    assert no_blink_char is not None
    assert blink_char is not None
    assert no_blink_char != blink_char
    assert blink_char == "─"


# ---------------------------------------------------------------------------
# IMMINENT_DEEP alpha pulse
# ---------------------------------------------------------------------------

def test_imminent_eye_alpha_pulses():
    w, h = 80, 24
    effect = MascotEffect(idle_secs=0)
    effect.on_pty_update(make_pty_update(w, h))

    # Advance to IMMINENT_DEEP (tick 75 in demo mode)
    assert run_to_phase(effect, Phase.IMMINENT_DEEP)

    corner_x = w - FACE_W - MARGIN
    corner_y = h - FACE_H - MARGIN
    eye_pos = (corner_x, corner_y + 1)

    alphas = set()
    for _ in range(EYE_PULSE_PERIOD):
        outputs = effect.tick()
        a = alpha_at(outputs, eye_pos)
        if a is not None:
            alphas.add(round(a, 4))

    assert len(alphas) > 1, "Eye alpha should vary across one pulse period"


# ---------------------------------------------------------------------------
# CACKLING frame alternation
# ---------------------------------------------------------------------------

def test_cackling_alternates_frames():
    w, h = 80, 24
    effect = MascotEffect(idle_secs=0)
    effect.on_pty_update(make_pty_update(w, h))

    assert run_to_phase(effect, Phase.CACKLING)

    corner_x = w - FACE_W - MARGIN
    corner_y = h - FACE_H - MARGIN
    top_left = (corner_x, corner_y)

    chars = set()
    for _ in range(CACKLE_FLIP_TICKS * 4):
        outputs = effect.tick()
        ch = char_at(outputs, top_left)
        if ch is not None:
            chars.add(ch)

    assert len(chars) == 2, f"Expected two alternating corner chars, got: {chars}"
    assert "╭" in chars
    assert "╔" in chars


# ---------------------------------------------------------------------------
# Demo mode reaches DONE; live mode loops
# ---------------------------------------------------------------------------

def test_demo_mode_reaches_done():
    effect = MascotEffect(idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))

    cackle_end = (
        DEMO_WATCHING_TICKS
        + DEMO_IMMINENT_EARLY_TICKS
        + DEMO_IMMINENT_DEEP_TICKS
        + DEMO_CACKLING_TICKS
    )
    for _ in range(cackle_end):
        effect.tick()

    assert effect.phase == Phase.DONE
    assert effect.tick() == []


def test_live_mode_loops():
    idle_secs = 10
    effect = MascotEffect(idle_secs=idle_secs)
    effect.on_pty_update(make_pty_update(80, 24))

    cackle_end = round(idle_secs * 1.30 * FPS) + 90
    for _ in range(cackle_end):
        effect.tick()

    assert effect.phase == Phase.WATCHING


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def test_resize_without_pty_update_triggers_rendering():
    """Overlay plugins may receive tty_resize but never pty_update."""
    effect = MascotEffect(idle_secs=300)
    effect.on_resize(TTYResize(width=80, height=24))
    outputs = effect.tick()
    assert len(outputs) == 1
    assert isinstance(outputs[0], OutputCells)
    assert len(outputs[0].cells) > 0


def test_resize_updates_face_position():
    w, h = 80, 24
    effect = MascotEffect(idle_secs=300)
    effect.on_pty_update(make_pty_update(w, h))
    effect.tick()

    new_w, new_h = 40, 12
    effect.on_resize(TTYResize(width=new_w, height=new_h))
    outputs = effect.tick()

    for out in outputs:
        if isinstance(out, OutputCells):
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < new_w
                assert 0 <= y < new_h


# ---------------------------------------------------------------------------
# Small terminal
# ---------------------------------------------------------------------------

def test_small_terminal_no_output():
    effect = MascotEffect(idle_secs=0)
    effect.on_pty_update(make_pty_update(3, 3))
    for _ in range(10):
        assert effect.tick() == []


# ---------------------------------------------------------------------------
# Wire format via step()
# ---------------------------------------------------------------------------

def test_step_wire_format():
    effect = MascotEffect(idle_secs=0)
    outputs = step(effect, [make_pty_json(80, 24)])
    assert len(outputs) > 0

    parsed = json.loads(outputs[0])
    assert "output_cells" in parsed
    assert isinstance(parsed["output_cells"], list)
    assert len(parsed["output_cells"]) > 0

    cell = parsed["output_cells"][0]
    assert "character" in cell
    assert "coordinates" in cell
    assert isinstance(cell["coordinates"], list)
    assert len(cell["coordinates"]) == 2
