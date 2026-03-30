"""Tests for clippy.effects.fire — FireEffect."""
import json

import pytest

from clippy.effects.fire import (
    BURN_DURATION,
    CANCEL_FADE_DURATION,
    CHARRED_TIERS,
    DECAY_MAX_TICKS,
    DECAY_MIN_TICKS,
    EMBER_EXTINGUISH_TIER,
    EMBER_LIFETIME,
    EMBER_PROB,
    SMOKE_DECAY_TICKS,
    CHARRED,
    BURNING as BURNING_STATE,
    FireEffect,
    Phase,
    SmokeParticle,
    heat_to_char,
    heat_to_color,
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
    """Advance the effect by N ticks, returning all outputs."""
    results = []
    for _ in range(ticks):
        results.extend(effect.tick())
    return results


def run_to_phase(effect, target_phase, max_ticks=800):
    """Advance until the target phase is reached or max_ticks exceeded."""
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
    """All cell coordinates must be within terminal dimensions (including smoke in WASTELAND)."""
    effect = FireEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(800):
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
    effect = FireEffect(seed=seed, idle_secs=0)
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
    effect = FireEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(50):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)


@pytest.mark.parametrize("seed", SEEDS)
def test_liveness(seed):
    """At least one non-empty frame in first 10 ticks after PTYUpdate."""
    effect = FireEffect(seed=seed, idle_secs=0)
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
    """Effect reaches DONE within bounded ticks (extended for ember lifetime)."""
    effect = FireEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=1500)
    assert reached_done, f"Effect did not reach DONE in 1500 ticks, stuck at {effect.phase.name}"


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

def test_idle_returns_empty():
    """tick() returns [] before any PTYUpdate."""
    effect = FireEffect(seed=0, idle_secs=0)
    assert effect.tick() == []
    assert effect.phase == Phase.IDLE


def test_ignition_on_first_update():
    """Non-empty output after first PTYUpdate + tick."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # idle_secs=0: first tick starts effect
    assert effect.phase == Phase.SPREADING
    outputs = effect.tick()
    assert len(outputs) > 0


def test_phases_progress():
    """Phase only moves forward (monotonically increasing, except resize regression)."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    effect.tick()  # start effect
    prev_phase = effect.phase
    for _ in range(600):
        effect.tick()
        current = effect.phase
        assert current >= prev_phase, (
            f"Phase regressed from {Phase(prev_phase).name} to {Phase(current).name}"
        )
        prev_phase = current
        if current == Phase.DONE:
            break
    assert effect.phase == Phase.DONE


def test_wasteland_decays():
    """Charred cells decay through tiers and effect eventually transitions to DONE."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(10, 4))

    # Run until WASTELAND
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # _charred_count should be > 0 at WASTELAND entry
    assert effect._charred_count > 0

    # WASTELAND should eventually transition to DONE as cells decay away
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=600)
    assert reached_done, "WASTELAND did not decay to DONE"


def test_done_returns_empty():
    """tick() returns [] after full lifecycle."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(10, 4))
    assert run_to_phase(effect, Phase.DONE, max_ticks=1000)
    assert effect.tick() == []
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Glyph decay
# ---------------------------------------------------------------------------

def test_initial_glyph_from_heavy_half():
    """Cells that just became CHARRED get tiers from the heavy half of CHARRED_TIERS."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    effect.tick()  # start effect (idle_secs=0: first tick initializes grids)
    heavy_limit = len(CHARRED_TIERS) // 2
    found = False

    for _ in range(400):
        # Snapshot cell states before tick to detect BURNING→CHARRED transitions
        prev_state = [row[:] for row in effect._cell_state]
        effect.tick()
        for y in range(effect._height):
            for x in range(effect._width):
                if prev_state[y][x] == BURNING_STATE and effect._cell_state[y][x] == CHARRED:
                    tier = effect._charred_tier[y][x]
                    assert 0 <= tier < heavy_limit, (
                        f"Initial charred tier {tier} not in heavy half [0, {heavy_limit})"
                    )
                    found = True
        if found:
            break

    assert found, "No BURNING→CHARRED transition observed in 400 ticks"


def test_glyph_decays_over_time():
    """A charred cell's tier advances after its decay interval elapses."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(10, 4))
    effect.tick()  # start effect

    # Find the first BURNING→CHARRED transition
    tracked_cell = None
    for _ in range(500):
        prev_state = [row[:] for row in effect._cell_state]
        effect.tick()
        if tracked_cell is None:
            for y in range(effect._height):
                for x in range(effect._width):
                    if prev_state[y][x] == BURNING_STATE and effect._cell_state[y][x] == CHARRED:
                        tracked_cell = (x, y)
                        break
                if tracked_cell is not None:
                    break
        if tracked_cell is not None:
            break

    assert tracked_cell is not None, "No BURNING→CHARRED transition observed in 500 ticks"
    tx, ty = tracked_cell
    initial_tier = effect._charred_tier[ty][tx]

    # After DECAY_MAX_TICKS + 1 ticks the decay interval must have elapsed
    for _ in range(DECAY_MAX_TICKS + 1):
        effect.tick()

    new_tier = effect._charred_tier[ty][tx]
    assert new_tier > initial_tier, (
        f"Charred cell tier did not increase: still {new_tier} after {DECAY_MAX_TICKS + 1} ticks"
    )


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def test_resize_preserves_state():
    """Existing burning cells survive resize."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    advance(effect, 10)
    assert effect._burning_count > 0
    old_burning = effect._burning_count

    # Resize larger
    effect.on_resize(TTYResize(width=30, height=10))
    # Burning cells should be preserved (at least some)
    assert effect._burning_count > 0
    assert effect._burning_count <= old_burning  # Can't gain burning cells from resize


def test_resize_no_oob():
    """No out-of-bounds coordinates after resize."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    advance(effect, 20)

    # Shrink
    effect.on_resize(TTYResize(width=20, height=6))
    for _ in range(20):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 6, f"y={y} OOB after resize"


def test_resize_grows_regresses_to_spreading():
    """Growing terminal during WASTELAND regresses to SPREADING."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(10, 4))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600)

    # Grow terminal — new CLEAR cells should regress to SPREADING
    effect.on_resize(TTYResize(width=20, height=8))
    assert effect.phase == Phase.SPREADING


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_seeded_deterministic():
    """Same seed produces identical first 5 frames."""
    def collect_frames(seed):
        effect = FireEffect(seed=seed, idle_secs=0)
        effect.on_pty_update(make_pty_update(20, 8))
        frames = []
        for _ in range(5):
            outputs = effect.tick()
            frame_data = []
            for out in outputs:
                for cell in out.cells:
                    frame_data.append((
                        cell.character,
                        cell.coordinates,
                        cell.fg,
                        cell.bg,
                    ))
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
    effect = FireEffect(seed=0, idle_secs=0)

    # First step: PTYUpdate sets idle_until; tick starts effect but returns []
    step(effect, [make_pty_json(40, 12)])

    # Second step: first real tick after effect starts
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

def test_heat_to_color_extremes():
    """Boundary colors are correct."""
    # Very high heat → white-hot
    c = heat_to_color(1.0)
    assert c == (1.0, 1.0, 0.9, 1.0)

    # Very low heat → smoke gray
    c = heat_to_color(0.02)
    assert c == (0.5, 0.5, 0.55, 1.0)


def test_heat_to_char_mapping():
    """Characters match expected thresholds."""
    assert heat_to_char(0.9) == "█"
    assert heat_to_char(0.65) == "▓"
    assert heat_to_char(0.5) == "▒"
    assert heat_to_char(0.3) == "░"
    assert heat_to_char(0.15) == "·"
    assert heat_to_char(0.05) == "•"
    assert heat_to_char(0.01) == " "


# ---------------------------------------------------------------------------
# Smouldering embers
# ---------------------------------------------------------------------------

def test_ember_creation_rarity():
    """Ember birth rate is well below 1% of BURNING→CHARRED transitions."""
    effect = FireEffect(seed=7, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    effect.tick()  # start effect

    transitions = 0
    ember_births = 0
    for _ in range(1000):
        prev_state = [row[:] for row in effect._cell_state]
        effect.tick()
        for y in range(effect._height):
            for x in range(effect._width):
                if prev_state[y][x] == BURNING_STATE and effect._cell_state[y][x] == CHARRED:
                    transitions += 1
                    if effect._is_ember[y][x]:
                        ember_births += 1
        if effect.phase == Phase.DONE:
            break

    if transitions > 0:
        rate = ember_births / transitions
        assert rate < 0.01, f"Ember birth rate {rate:.4f} exceeds 1% of transitions"


@pytest.mark.parametrize("seed", SEEDS)
def test_ember_colors_in_range(seed):
    """Ember cell colors must stay within [0.0, 1.0] during WASTELAND."""
    effect = FireEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    for _ in range(800):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                for color in (cell.fg, cell.bg):
                    if color is not None:
                        for i, component in enumerate(color):
                            assert 0.0 <= component <= 1.0, (
                                f"Color component {i}={component} out of range "
                                f"at {cell.coordinates} (phase={effect.phase.name})"
                            )


def test_ember_extinguishes_to_charred():
    """An injected ember extinguishes to CHARRED at EMBER_EXTINGUISH_TIER after EMBER_LIFETIME ticks."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    # Run until WASTELAND so all burning cells are gone
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Inject a lone ember at a CHARRED cell
    x, y = 5, 3
    effect._cell_state[y][x] = CHARRED
    effect._is_ember[y][x] = True
    effect._ember_ignition_tick[y][x] = effect._tick_count - EMBER_LIFETIME  # already aged out
    effect._ember_count += 1
    effect._ember_positions.add((x, y))

    effect.tick()

    assert not effect._is_ember[y][x], "Ember should have extinguished"
    assert effect._charred_tier[y][x] == EMBER_EXTINGUISH_TIER, (
        f"Expected tier {EMBER_EXTINGUISH_TIER}, got {effect._charred_tier[y][x]}"
    )
    assert effect._charred_count > 0, "_charred_count should have been incremented"


def test_smoke_emits_above_ember():
    """After several ticks an active ember should have emitted at least one smoke particle."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Inject ember not at top row (needs y > 0 to emit smoke above it)
    x, y = 10, 5
    effect._cell_state[y][x] = CHARRED
    effect._is_ember[y][x] = True
    effect._ember_ignition_tick[y][x] = effect._tick_count
    effect._ember_count += 1
    effect._ember_positions.add((x, y))

    for _ in range(50):
        effect.tick()
        if effect._smoke:
            break

    assert effect._smoke or not effect._is_ember[y][x], (
        "No smoke emitted in 50 ticks and ember still active"
    )
    # More directly: check at least one particle ever had fy <= 5
    # (we can't inspect history, so just confirm smoke appeared at some point)
    # The loop break ensures we got here only if smoke was found
    assert any(p.fy <= y for p in effect._smoke) or not effect._is_ember[y][x]


def test_smoke_rises_and_clears():
    """A smoke particle eventually rises out of the grid and is removed."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Inject a smoke particle. It will either rise off-screen or decay through tiers.
    # SMOKE_DECAY_TICKS=20, len(CHARRED_TIERS)=7: particle decays out after ≤140 ticks.
    effect._smoke = [SmokeParticle(
        fx=5.0, fy=2.0, vx=0.0, vy=0.0, tier=4,
        last_decay_tick=effect._tick_count,
    )]

    for _ in range(SMOKE_DECAY_TICKS * len(CHARRED_TIERS) + 10):
        effect.tick()

    # Particle should have risen off-screen or decayed away (not still at origin at y=2)
    still_at_origin = any(round(p.fx) == 5 and round(p.fy) == 2 for p in effect._smoke)
    assert not still_at_origin, "Smoke particle did not move from y=2 after enough ticks"


def test_wasteland_blocked_by_live_ember():
    """WASTELAND does not transition to DONE while an ember is still active."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Force charred_count to 0 and drain smoke, then inject a live ember
    effect._charred_count = 0
    effect._smoke = []
    x, y = 5, 3
    effect._cell_state[y][x] = CHARRED
    effect._is_ember[y][x] = True
    effect._ember_ignition_tick[y][x] = effect._tick_count  # freshly ignited
    effect._ember_count = 1
    effect._ember_positions.add((x, y))

    effect.tick()

    assert effect.phase == Phase.WASTELAND, (
        f"Phase transitioned to {effect.phase.name} despite live ember"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_ember_count_invariant(seed):
    """_ember_count always equals the number of True entries in _is_ember."""
    effect = FireEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    for _ in range(800):
        if effect.phase == Phase.DONE:
            break
        effect.tick()
        actual = sum(
            effect._is_ember[y][x]
            for y in range(effect._height)
            for x in range(effect._width)
        )
        assert effect._ember_count == actual, (
            f"_ember_count={effect._ember_count} != actual={actual} at tick {effect._tick_count}"
        )


# ---------------------------------------------------------------------------
# Cursor-shake CANCEL_FADING
# ---------------------------------------------------------------------------

def test_cancel_triggers_cancel_fading():
    """cancel() during SPREADING transitions immediately to CANCEL_FADING."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # idle_secs=0: starts effect
    assert effect.phase == Phase.SPREADING

    effect.cancel()
    assert effect.phase == Phase.CANCEL_FADING


def test_cancel_fading_fades_and_reaches_done():
    """CANCEL_FADING decreases alpha and eventually reaches DONE."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()

    effect.cancel()
    assert effect.phase == Phase.CANCEL_FADING

    # Run for CANCEL_FADE_DURATION + a few extra ticks; phase should reach DONE
    for _ in range(CANCEL_FADE_DURATION + 5):
        effect.tick()
        if effect.phase == Phase.DONE:
            break

    assert effect.phase == Phase.DONE, (
        f"Expected DONE after CANCEL_FADING, got {effect.phase.name}"
    )


# ---------------------------------------------------------------------------
# BURN_DURATION governs BURNING→CHARRED transition
# ---------------------------------------------------------------------------

def test_burning_phase_bounded_by_burn_duration():
    """A cell that was BURNING transitions to CHARRED after BURN_DURATION ticks."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    effect.tick()  # start effect

    # Find a BURNING cell
    burning_cell = None
    for _ in range(50):
        effect.tick()
        for y in range(effect._height):
            for x in range(effect._width):
                if effect._cell_state[y][x] == BURNING_STATE:
                    burning_cell = (x, y)
                    break
            if burning_cell:
                break
        if burning_cell:
            break

    assert burning_cell is not None, "No BURNING cell found"
    bx, by = burning_cell
    ignition_tick = effect._ignition_tick[by][bx]

    # Tick until BURN_DURATION has elapsed for this cell
    for _ in range(BURN_DURATION + 5):
        effect.tick()

    age = effect._tick_count - ignition_tick
    assert age >= BURN_DURATION
    assert effect._cell_state[by][bx] == CHARRED, (
        f"Cell at ({bx},{by}) should be CHARRED after {age} ticks, "
        f"got state={effect._cell_state[by][bx]}"
    )


# ---------------------------------------------------------------------------
# CANCEL_FADING alpha decreases
# ---------------------------------------------------------------------------

def test_cancel_fading_alpha_decreases():
    """During CANCEL_FADING, at least one cell has fg alpha < 1.0."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect
    assert effect.phase == Phase.SPREADING

    effect.cancel()
    assert effect.phase == Phase.CANCEL_FADING

    found_dimmed = False
    for _ in range(CANCEL_FADE_DURATION):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                if cell.fg is not None and cell.fg[3] < 1.0:
                    found_dimmed = True
        if found_dimmed:
            break

    assert found_dimmed, "No dimmed cells observed during CANCEL_FADING"


# ---------------------------------------------------------------------------
# Nonzero idle_secs delays start
# ---------------------------------------------------------------------------

def test_nonzero_idle_secs_delays_start():
    """idle_secs=5 keeps effect in IDLE for at least 100 ticks after PTYUpdate."""
    effect = FireEffect(seed=42, idle_secs=5)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(100):
        effect.tick()
    assert effect.phase == Phase.IDLE, (
        f"Expected IDLE after 100 ticks with idle_secs=5, got {effect.phase.name}"
    )


def test_cancel_noop_in_idle():
    """cancel() during IDLE has no effect — phase stays IDLE."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect._idle_until = effect._tick_count + 10000  # far in the future
    assert effect.phase == Phase.IDLE
    effect.cancel()
    assert effect.phase == Phase.IDLE


def test_is_done_property():
    """is_done is True iff phase is DONE."""
    effect = FireEffect(seed=42, idle_secs=0)
    assert not effect.is_done
    effect.on_pty_update(make_pty_update(10, 4))
    run_to_phase(effect, Phase.DONE, max_ticks=1500)
    assert effect.is_done


# ---------------------------------------------------------------------------
# Delta rendering
# ---------------------------------------------------------------------------

def test_full_frame_coverage():
    """Every frame emits all visible cells (tattoy replaces the layer per message)."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Two consecutive WASTELAND frames should emit the same positions
    outputs_first = effect.tick()
    positions_first = {cell.coordinates for out in outputs_first for cell in out.cells}

    outputs_second = effect.tick()
    positions_second = {cell.coordinates for out in outputs_second for cell in out.cells}

    # Stable charred cells must appear in both frames
    stable = positions_first & positions_second
    assert len(stable) > 0, "No stable positions across frames"


def test_smoke_over_charred_restores():
    """When smoke moves off a charred cell, charred content reappears."""
    effect = FireEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.WASTELAND, max_ticks=600), "Never reached WASTELAND"

    # Find a charred cell that won't decay soon
    charred_pos = None
    for x, y in effect._charred_positions:
        if effect._charred_char[y][x] != " ":
            charred_pos = (x, y)
            break
    if charred_pos is None:
        pytest.skip("No non-blank charred cells available")

    cx, cy = charred_pos
    charred_char = effect._charred_char[cy][cx]

    # Place smoke on top of the charred cell
    from clippy.effects.fire import SmokeParticle
    effect._smoke = [SmokeParticle(
        fx=float(cx), fy=float(cy), vx=0.0, vy=0.0, tier=4,
        last_decay_tick=effect._tick_count,
    )]
    effect.tick()  # renders smoke at charred position

    # Move smoke away
    effect._smoke = [SmokeParticle(
        fx=float(cx + 5), fy=float(cy), vx=0.0, vy=0.0, tier=4,
        last_decay_tick=effect._tick_count,
    )]
    outputs = effect.tick()

    # Charred cell should be re-emitted at the old smoke position
    found_charred = False
    for out in outputs:
        for cell in out.cells:
            if cell.coordinates == charred_pos and cell.character == charred_char:
                found_charred = True
    assert found_charred, (
        f"Charred cell '{charred_char}' at {charred_pos} not re-emitted after smoke moved away"
    )


def test_delta_resize_clears_tracking():
    """No OOB ghost erasure after resize to smaller terminal."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    advance(effect, 20)  # build up render tracking state

    # Shrink terminal
    effect.on_resize(TTYResize(width=15, height=5))

    # Ticking after resize must not emit OOB coordinates
    for _ in range(10):
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 15, f"x={x} OOB after resize"
                assert 0 <= y < 5, f"y={y} OOB after resize"


# ---------------------------------------------------------------------------
# Heap-based decay
# ---------------------------------------------------------------------------

def test_heap_decay_reaches_done():
    """Effect still reaches DONE within bounded ticks using heap-based decay."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=1500)
    assert reached_done, f"Effect did not reach DONE in 1500 ticks, stuck at {effect.phase.name}"


# ---------------------------------------------------------------------------
# Coarser heat resolution
# ---------------------------------------------------------------------------

def test_coarse_heat_in_bounds():
    """Heat shimmer coordinates stay within terminal bounds with half-resolution propagation."""
    effect = FireEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(200):
        if effect.phase == Phase.DONE:
            break
        outputs = effect.tick()
        for out in outputs:
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"x={x} out of bounds"
                assert 0 <= y < 24, f"y={y} out of bounds"
