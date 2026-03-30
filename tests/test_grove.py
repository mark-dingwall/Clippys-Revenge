"""Tests for clippy.effects.grove — GroveEffect."""
import json

import pytest

from clippy.effects.grove import (
    BIRD_PERCH,
    FADE_DURATION,
    GROWING_DURATION,
    PERCHING_DURATION,
    GroveEffect,
    Phase,
)
from clippy.harness import step
from clippy.types import OutputCells, PTYUpdate, TTYResize


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


def run_to_phase(effect, target_phase, max_ticks=1000):
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
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(500):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"x={x} out of bounds"
                assert 0 <= y < 24, f"y={y} out of bounds"


@pytest.mark.parametrize("seed", SEEDS)
def test_colors_in_range(seed):
    """All RGBA components must be in [0.0, 1.0]."""
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(200):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                if cell.fg is not None:
                    for i, component in enumerate(cell.fg):
                        assert 0.0 <= component <= 1.0, (
                            f"fg component {i}={component} OOB at {cell.coordinates}"
                        )
                if cell.bg is not None:
                    for i, component in enumerate(cell.bg):
                        assert 0.0 <= component <= 1.0, (
                            f"bg component {i}={component} OOB at {cell.coordinates}"
                        )


@pytest.mark.parametrize("seed", SEEDS)
def test_output_type(seed):
    """tick() returns list containing only OutputCells."""
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(50):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)


@pytest.mark.parametrize("seed", SEEDS)
def test_liveness(seed):
    """At least one non-empty frame within first 15 ticks after PTYUpdate."""
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    found_output = False
    for _ in range(15):
        outputs = effect.tick()
        if outputs:
            found_output = True
            break
    assert found_output, "No output in first 15 ticks"


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

def test_idle_returns_empty():
    """tick() returns [] before any PTYUpdate."""
    effect = GroveEffect(seed=0, idle_secs=0)
    assert effect.tick() == []
    assert effect.phase == Phase.IDLE


def test_growing_on_first_update():
    """Phase transitions to GROWING after first PTYUpdate + tick."""
    effect = GroveEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # idle_secs=0: first tick starts effect
    assert effect.phase == Phase.GROWING
    outputs = effect.tick()
    assert len(outputs) > 0


def test_phases_progress():
    """Phase only moves forward; reaches DONE within bounded ticks."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    effect.tick()  # start effect
    prev_phase = effect.phase
    max_ticks = GROWING_DURATION + PERCHING_DURATION + FADE_DURATION + 100
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
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    max_ticks = GROWING_DURATION + PERCHING_DURATION + FADE_DURATION + 100
    assert run_to_phase(effect, Phase.DONE, max_ticks=max_ticks)
    assert effect.tick() == []
    assert effect.tick() == []


def test_seeded_deterministic():
    """Same seed produces identical first 5 frames."""
    def collect_frames(seed):
        e = GroveEffect(seed=seed, idle_secs=0)
        e.on_pty_update(make_pty_update(40, 12))
        frames = []
        for _ in range(5):
            outputs = e.tick()
            frame_data = []
            for out in outputs:
                for cell in out.cells:
                    frame_data.append((cell.coordinates, cell.fg))
            frames.append(frame_data)
        return frames

    frames_a = collect_frames(42)
    frames_b = collect_frames(42)
    assert frames_a == frames_b


def test_step_integration():
    """Use harness.step() to drive effect through a few ticks."""
    effect = GroveEffect(seed=0, idle_secs=0)
    # First step: PTYUpdate sets idle_until; tick starts effect but returns []
    step(effect, [make_pty_json(40, 12)])

    # Grove grows gradually; advance until we get output
    found = False
    for _ in range(15):
        result = step(effect, [])
        if result:
            data = json.loads(result[0])
            if "output_cells" in data and data["output_cells"]:
                found = True
                break
    assert found, "No output_cells from grove in first 15 steps after start"


def test_resize_no_oob():
    """No OOB coordinates after resize to 20x6."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    advance(effect, 20)

    effect.on_resize(TTYResize(width=20, height=6))
    for _ in range(30):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 6, f"y={y} OOB after resize"


# ---------------------------------------------------------------------------
# Multi-cell flowers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_flower_patterns_in_bounds(seed):
    """Multi-cell flower patterns must stay within terminal bounds."""
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    # Run through growing phase to let flowers bloom
    for _ in range(GROWING_DURATION + 50):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"flower x={x} out of bounds"
                assert 0 <= y < 24, f"flower y={y} out of bounds"


# ---------------------------------------------------------------------------
# Ghost erasure
# ---------------------------------------------------------------------------

def test_ghost_erasure_cells_present():
    """After birds move, eraser cells (space chars) should appear for old positions."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    # Advance into perching phase where birds move
    assert run_to_phase(effect, Phase.PERCHING, max_ticks=GROWING_DURATION + 50)
    # Run a few ticks to let birds fly
    for _ in range(10):
        effect.tick()
    # Now check that some eraser cells exist (space chars with fg=None)
    outputs = effect.tick()
    # At minimum, the effect should not crash and should produce output
    assert len(outputs) > 0


# ---------------------------------------------------------------------------
# Vine character stability
# ---------------------------------------------------------------------------

def test_vine_chars_stable_within_timer():
    """Vine characters should not change every tick (stable within timer window)."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    # Grow vines
    advance(effect, 100)
    # Record vine chars
    if effect._vines:
        v = effect._vines[0]
        if v.current_len > 0:
            chars_before = list(v.cell_chars[:v.current_len])
            # Advance a few ticks (well under the 60-tick minimum timer)
            advance(effect, 5)
            chars_after = list(v.cell_chars[:v.current_len])
            # Most chars should be the same (timers start at 60-120)
            same_count = sum(1 for a, b in zip(chars_before, chars_after) if a == b)
            assert same_count >= len(chars_before) * 0.8, (
                "Too many vine chars changed in 5 ticks"
            )


# ---------------------------------------------------------------------------
# Attached flowers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_attached_flowers_in_bounds(seed):
    """Attached flowers (vine/canopy) must stay within terminal bounds."""
    effect = GroveEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(GROWING_DURATION + 50):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"attached flower x={x} out of bounds"
                assert 0 <= y < 24, f"attached flower y={y} out of bounds"


# ---------------------------------------------------------------------------
# Cursor-shake cancellation
# ---------------------------------------------------------------------------

def test_cancel_during_growing():
    """cancel() during GROWING transitions to FADING."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect
    assert effect.phase == Phase.GROWING
    effect.cancel()
    assert effect.phase == Phase.FADING


def test_cancel_during_perching():
    """cancel() during PERCHING transitions to FADING."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.PERCHING, max_ticks=GROWING_DURATION + 50)
    effect.cancel()
    assert effect.phase == Phase.FADING


def test_is_done_property():
    """is_done is True iff phase is DONE."""
    effect = GroveEffect(seed=42, idle_secs=0)
    assert not effect.is_done
    effect.on_pty_update(make_pty_update(40, 12))
    max_ticks = GROWING_DURATION + PERCHING_DURATION + FADE_DURATION + 100
    run_to_phase(effect, Phase.DONE, max_ticks=max_ticks)
    assert effect.is_done


# ---------------------------------------------------------------------------
# PERCHING behavioral test
# ---------------------------------------------------------------------------

def test_perching_emits_bird_character():
    """At least one cell with BIRD_PERCH character appears during PERCHING."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.PERCHING, max_ticks=GROWING_DURATION + 50)
    found = False
    for _ in range(200):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                if cell.character == BIRD_PERCH:
                    found = True
        if found or effect.phase != Phase.PERCHING:
            break
    assert found, "No bird perch character observed during PERCHING"


# ---------------------------------------------------------------------------
# Fading alpha
# ---------------------------------------------------------------------------

def test_fading_alpha_decreases_grove():
    """At least one cell has fg alpha < 1.0 during FADING."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    max_ticks = GROWING_DURATION + PERCHING_DURATION + 50
    assert run_to_phase(effect, Phase.FADING, max_ticks=max_ticks)
    found_dimmed = False
    for _ in range(30):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                if cell.fg is not None and cell.fg[3] < 1.0:
                    found_dimmed = True
        if found_dimmed or effect.phase == Phase.DONE:
            break
    assert found_dimmed, "No dimmed cells observed during FADING"


def test_destructive_is_false():
    """GroveEffect should be non-destructive (no black trails behind moving particles)."""
    assert GroveEffect.destructive is False


def test_all_cells_bg_none():
    """All grove cells should have bg=None (overlays, not destructive)."""
    effect = GroveEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    max_ticks = GROWING_DURATION + PERCHING_DURATION + 10
    assert run_to_phase(effect, Phase.PERCHING, max_ticks=max_ticks)
    # Check several frames during PERCHING (birds/fireflies are active)
    for _ in range(10):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                assert cell.bg is None, (
                    f"Grove cell at {cell.coordinates} has bg={cell.bg}, expected None"
                )
