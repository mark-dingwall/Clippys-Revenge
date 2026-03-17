"""Tests for clippy.effects.microbes — MicrobesEffect."""
import json

import pytest

from clippy.effects.microbes import (
    FADE_DURATION,
    SWARMING_DURATION,
    MicrobesEffect,
    Phase,
    _catmull_rom,
    _hsb_to_rgb,
)
from clippy.harness import step
from clippy.types import OutputPixels, Pixel, PTYUpdate, TTYResize


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
    """All pixel coordinates must be within [0, width) x [0, height*2)."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(100):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputPixels)
            for pixel in out.pixels:
                x, y = pixel.coordinates
                assert 0 <= x < 80, f"x={x} out of bounds"
                assert 0 <= y < 48, f"y={y} out of bounds (height*2=48)"


@pytest.mark.parametrize("seed", SEEDS)
def test_colors_in_range(seed):
    """All RGBA components must be in [0.0, 1.0]."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(100):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputPixels)
            for pixel in out.pixels:
                if pixel.color is not None:
                    for i, component in enumerate(pixel.color):
                        assert 0.0 <= component <= 1.0, (
                            f"Color component {i}={component} out of range "
                            f"at ({pixel.coordinates})"
                        )


@pytest.mark.parametrize("seed", SEEDS)
def test_output_type(seed):
    """tick() returns list containing only OutputPixels."""
    effect = MicrobesEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(50):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputPixels)


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
            for pixel in out.pixels:
                x, y = pixel.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 12, f"y={y} OOB after resize (height*2=12)"


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
                for pixel in out.pixels:
                    frame_data.append((pixel.coordinates, pixel.color))
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
    assert "output_pixels" in data
    pixels = data["output_pixels"]
    assert isinstance(pixels, list)
    assert len(pixels) > 0

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


# ---------------------------------------------------------------------------
# Cursor-shake cancellation
# ---------------------------------------------------------------------------

def _shake_msgs():
    return [make_pty_json(cursor=(x, 5)) for x in [10, 30, 10, 30, 10]]


def test_cursor_shake_cancels_microbes():
    """Cursor shake during SWARMING transitions to FADING."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect
    assert effect.phase == Phase.SWARMING
    step(effect, _shake_msgs())
    assert effect.phase == Phase.FADING


# ---------------------------------------------------------------------------
# FADING alpha + ghost pixels
# ---------------------------------------------------------------------------

def test_fading_alpha_decreases():
    """At least one pixel has color alpha < 1.0 during FADING."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.FADING, max_ticks=SWARMING_DURATION + 50)
    found_dimmed = False
    for _ in range(30):
        outputs = effect.tick()
        for out in outputs:
            for pixel in out.pixels:
                if pixel.color is not None and pixel.color[3] < 1.0:
                    found_dimmed = True
        if found_dimmed or effect.phase == Phase.DONE:
            break
    assert found_dimmed, "No dimmed pixels observed during FADING"


def test_ghost_pixels_emitted():
    """At least one Pixel(color=None) appears after SWARMING starts."""
    effect = MicrobesEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect
    assert effect.phase == Phase.SWARMING
    found_ghost = False
    for _ in range(SWARMING_DURATION + FADE_DURATION):
        outputs = effect.tick()
        for out in outputs:
            for pixel in out.pixels:
                if pixel.color is None:
                    found_ghost = True
        if found_ghost or effect.phase == Phase.DONE:
            break
    assert found_ghost, "No ghost pixel (color=None) observed"
