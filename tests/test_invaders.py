"""Tests for clippy.effects.invaders — InvadersEffect."""
import json

import pytest

from clippy.effects.invaders import (
    ALIEN_COLORS,
    ALIEN_KILL_COLOR,
    ALIEN_SPRITE_HEIGHT,
    ALIEN_SPRITE_WIDTH,
    BOMB_COLOR,
    BOMBARDMENT_BOMB_RATE,
    DEFENDER_SHOT_COLOR,
    FADE_DURATION,
    FLUNG_COLOR,
    RUBBLE_COLOR,
    InvadersEffect,
    Phase,
    _AlienKill,
    _DefenderShot,
    _Alien,
    _make_sprite,
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
    """Advance the effect by N ticks, returning all flattened cells."""
    cells = []
    for _ in range(ticks):
        for out in effect.tick():
            if isinstance(out, OutputCells):
                cells.extend(out.cells)
    return cells


def run_to_phase(effect, target_phase, max_ticks=3000):
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
    """All cell coordinates must be within terminal dimensions."""
    effect = InvadersEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(200):
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
    effect = InvadersEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(200):
        outputs = effect.tick()
        for out in outputs:
            assert isinstance(out, OutputCells)
            for cell in out.cells:
                for color in (cell.fg, cell.bg):
                    if color is not None:
                        for i, component in enumerate(color):
                            assert 0.0 <= component <= 1.0, (
                                f"Color component {i}={component} out of range "
                                f"at {cell.coordinates}"
                            )


@pytest.mark.parametrize("seed", SEEDS)
def test_output_type(seed):
    """tick() returns list containing only OutputCells."""
    effect = InvadersEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(200):
        for out in effect.tick():
            assert isinstance(out, OutputCells)


@pytest.mark.parametrize("seed", SEEDS)
def test_liveness(seed):
    """Non-empty frame within 3 ticks of PTYUpdate."""
    effect = InvadersEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    found_output = False
    for _ in range(3):
        if effect.tick():
            found_output = True
            break
    assert found_output, "No output in first 3 ticks"


@pytest.mark.parametrize("seed", SEEDS)
def test_eventual_completion(seed):
    """Effect reaches DONE within 3000 ticks on a small terminal."""
    effect = InvadersEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=3000)
    assert reached_done, (
        f"Effect did not reach DONE in 3000 ticks, stuck at {effect.phase.name}"
    )


# ---------------------------------------------------------------------------
# Phase / lifecycle tests
# ---------------------------------------------------------------------------

def test_idle_returns_empty():
    """tick() returns [] before any PTYUpdate."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    assert effect.tick() == []
    assert effect.phase == Phase.IDLE


def test_bombardment_on_first_update():
    """Phase is BOMBARDMENT after PTYUpdate + first tick; second tick produces output."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # idle_secs=0: first tick starts effect
    assert effect.phase == Phase.BOMBARDMENT
    outputs = effect.tick()
    assert len(outputs) > 0


def test_phases_monotonic():
    """Phase value never decreases (IDLE < BOMBARDMENT < ACTIVE < FADING < DONE)."""
    effect = InvadersEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    prev_phase = effect.phase
    for _ in range(500):
        effect.tick()
        current = effect.phase
        assert current >= prev_phase, (
            f"Phase regressed from {Phase(prev_phase).name} to {Phase(current).name}"
        )
        prev_phase = current
        if current == Phase.DONE:
            break


def test_done_returns_empty():
    """tick() returns [] after DONE phase."""
    effect = InvadersEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))
    assert run_to_phase(effect, Phase.DONE, max_ticks=3000)
    assert effect.tick() == []
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_top_zone_cleared():
    """Rubble accumulates in the top zone during bombardment (no solid overlay)."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    top_zone_height = effect._top_zone_height
    # Run enough ticks for bombs to spawn (every BOMBARDMENT_BOMB_RATE ticks) and detonate
    found_top_content = False
    for _ in range(BOMBARDMENT_BOMB_RATE * 20):
        outputs = effect.tick()
        if effect.phase != Phase.BOMBARDMENT:
            break
        all_cells = [c for out in outputs for c in out.cells]
        top_ys = {c.coordinates[1] for c in all_cells if c.coordinates[1] < top_zone_height}
        if top_ys:
            found_top_content = True
            break
    assert found_top_content, "No content found in top zone during bombardment"


def test_rubble_only_in_code_zone():
    """Gray (rubble) cells from active-phase bombs only appear at y >= code_zone_start.

    Bombardment rubble intentionally spans the whole screen and fades out;
    we skip the check while _bombard_rubble is still present.
    """
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    code_zone_start = effect._code_zone_start

    # Run enough ticks that some rubble appears
    for _ in range(300):
        for out in effect.tick():
            for cell in out.cells:
                fg = cell.fg
                if fg is not None and _is_approx_color(fg, RUBBLE_COLOR):
                    # Skip while bombardment rubble (whole-screen) is still present/fading
                    if effect._bombard_rubble:
                        continue
                    x, y = cell.coordinates
                    assert y >= code_zone_start, (
                        f"Rubble at y={y} above code_zone_start={code_zone_start}"
                    )


def test_bombs_in_bounds():
    """Yellow (bomb) cells always have valid coordinates."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(250):
        for out in effect.tick():
            for cell in out.cells:
                fg = cell.fg
                if fg is not None and _is_approx_color(fg, BOMB_COLOR):
                    x, y = cell.coordinates
                    assert 0 <= x < 80, f"Bomb x={x} OOB"
                    assert 0 <= y < 24, f"Bomb y={y} OOB"


def test_alien_cells_in_top_zone():
    """Alien cells only appear at y < code_zone_start during ACTIVE phase."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.ACTIVE, max_ticks=500), "Never reached ACTIVE"
    code_zone_start = effect._code_zone_start
    for _ in range(100):
        for out in effect.tick():
            for cell in out.cells:
                fg = cell.fg
                if fg is not None and _is_approx_any_alien_color(fg):
                    x, y = cell.coordinates
                    assert y < code_zone_start, (
                        f"Alien cell at y={y} >= code_zone_start={code_zone_start}"
                    )
        if effect.phase != Phase.ACTIVE:
            break


def test_fading_alpha_decreases():
    """Once FADING, cells have alpha < 1.0; eventually transitions to DONE."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8))

    # Advance to FADING
    reached_fading = run_to_phase(effect, Phase.FADING, max_ticks=3000)
    assert reached_fading, "Never reached FADING"

    # Check that some cell has alpha < 1.0 during FADING
    found_dimmed = False
    for _ in range(FADE_DURATION + 5):
        for out in effect.tick():
            for cell in out.cells:
                if cell.fg is not None and cell.fg[3] < 1.0:
                    found_dimmed = True
        if effect.phase == Phase.DONE:
            break

    assert found_dimmed, "No dimmed cells observed during FADING"
    assert effect.phase == Phase.DONE, f"Expected DONE, got {effect.phase.name}"


def test_sprite_symmetry():
    """Generated sprites are left-right symmetric: row[0]==row[4] and row[1]==row[3]."""
    rng_seed = 0
    import random
    rng = random.Random(rng_seed)
    for _ in range(20):
        genome = rng.getrandbits(12)
        sprite = _make_sprite(genome)
        for row_idx, row in enumerate(sprite):
            assert len(row) == 5, f"Sprite row {row_idx} has length {len(row)}, expected 5"
            assert row[0] == row[4], (
                f"Sprite not symmetric at row {row_idx}: '{row[0]}' != '{row[4]}'"
            )
            assert row[1] == row[3], (
                f"Sprite not symmetric at row {row_idx}: '{row[1]}' != '{row[3]}'"
            )


def test_flung_chars_in_bounds():
    """Flung characters (text debris from mid-screen bomb hits) stay in bounds."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))

    # Seed the code zone with PTY text so bombs have content to fling
    cz = effect._code_zone_start
    for x in range(0, 80, 2):
        effect._pty_cells[(x, cz + 2)] = "x"
        effect._pty_cells[(x, cz + 4)] = "y"

    for _ in range(500):
        outputs = effect.tick()
        for out in outputs:
            if isinstance(out, OutputCells):
                for cell in out.cells:
                    x, y = cell.coordinates
                    assert 0 <= x < 80, f"Cell x={x} OOB"
                    assert 0 <= y < 24, f"Cell y={y} OOB"
        if effect.phase == Phase.DONE:
            break


# ---------------------------------------------------------------------------
# Resize tests
# ---------------------------------------------------------------------------

def test_resize_no_oob():
    """No out-of-bounds coordinates after shrinking the terminal."""
    effect = InvadersEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12))
    advance(effect, 20)

    effect.on_resize(TTYResize(width=20, height=6))
    for _ in range(20):
        for out in effect.tick():
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 6, f"y={y} OOB after resize"


def test_resize_prunes_rubble():
    """Rubble outside new bounds is dropped after resize."""
    effect = InvadersEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()  # start effect (needed so on_resize isn't skipped for IDLE)

    # Manually inject some rubble outside the future new bounds
    effect._rubble[(60, 20)] = "#"
    effect._rubble[(70, 22)] = "%"
    effect._rubble[(10, 15)] = "&"
    effect._rubble_count = len(effect._rubble)

    effect.on_resize(TTYResize(width=40, height=12))

    for (x, y) in effect._rubble:
        assert 0 <= x < 40, f"Rubble x={x} not pruned after resize"
        assert y < 12, f"Rubble y={y} not pruned after resize"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_seeded_deterministic():
    """Same seed produces identical first 5 frames."""
    def collect_frames(seed):
        effect = InvadersEffect(seed=seed, idle_secs=0)
        effect.on_pty_update(make_pty_update(80, 24))
        frames = []
        for _ in range(5):
            frame_data = []
            for out in effect.tick():
                if isinstance(out, OutputCells):
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
# Harness integration
# ---------------------------------------------------------------------------

def test_step_integration():
    """harness.step() returns output_cells as a direct array (not nested object)."""
    effect = InvadersEffect(seed=0, idle_secs=0)

    # First step triggers PTY update + one tick; advance until bombs spawn so output is non-empty
    result = step(effect, [make_pty_json(80, 24)])
    for _ in range(BOMBARDMENT_BOMB_RATE * 5):
        more = step(effect, [])
        result.extend(more)

    assert len(result) >= 1
    # Parse all frames and find one with cells
    found_cells = False
    for line in result:
        data = json.loads(line)
        if "output_cells" not in data:
            continue
        cells = data["output_cells"]
        assert isinstance(cells, list), "output_cells must be a direct array"
        if cells:
            found_cells = True
    assert found_cells, "No non-empty output_cells frame produced"


# ---------------------------------------------------------------------------
# Round 3 tests
# ---------------------------------------------------------------------------

def test_bombardment_flings_chars():
    """Bombardment detonations eject flung chars (same as active-phase bombs)."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    # Seed PTY content throughout top zone so detonate() has chars to fling
    for y in range(effect._top_zone_height):
        for x in range(0, 80, 2):
            effect._pty_cells[(x, y)] = "A"
    # Run enough ticks for bombs to detonate
    for _ in range(BOMBARDMENT_BOMB_RATE * 6):
        effect.tick()
    assert effect._flung, "No chars were flung during bombardment"


def test_defender_shots_appear():
    """White defender shot cells appear during ACTIVE phase."""
    effect = InvadersEffect(seed=7, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.ACTIVE, max_ticks=500), "Never reached ACTIVE"
    found = False
    for _ in range(200):
        for out in effect.tick():
            for cell in out.cells:
                if cell.fg and _is_approx_color(cell.fg, DEFENDER_SHOT_COLOR):
                    found = True
        if found or effect.phase != Phase.ACTIVE:
            break
    assert found, "No defender shot cells observed during ACTIVE phase"


def test_defender_shot_kills_alien():
    """A defender shot that overlaps an alien removes it and records an AlienKill."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.ACTIVE, max_ticks=500), "Never reached ACTIVE"
    # Clear existing state and plant a single alien at a known location
    effect._aliens = []
    effect._defender_shots = []
    effect._alien_kills = []
    lane = 0
    lane_y = effect._lane_y(lane)
    alien = _Alien(lane=lane, x=20, dx=1,
                   sprite_idx=0, color=ALIEN_COLORS[0],
                   anim_frame=0, anim_timer=0)
    effect._aliens = [alien]
    # Plant a shot one row below the alien's top — it moves up by 1 on next tick
    shot_x = 22   # within [20, 25)
    shot_y = lane_y + 1  # will move to lane_y after -=1
    effect._defender_shots = [_DefenderShot(x=shot_x, y=shot_y)]
    before_count = len(effect._aliens)
    effect.tick()
    assert len(effect._aliens) < before_count, "Alien was not removed after hit"
    assert len(effect._alien_kills) > 0, "No AlienKill recorded after hit"


def test_alien_kill_fireball_renders():
    """An injected AlienKill produces green fireball cells in the output."""
    effect = InvadersEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, Phase.ACTIVE, max_ticks=500), "Never reached ACTIVE"
    effect._alien_kills = [_AlienKill(x=40, y=4, born_tick=effect._tick_count)]
    found_fireball = False
    for _ in range(6):
        for out in effect.tick():
            for cell in out.cells:
                if cell.fg and _is_approx_color(cell.fg, ALIEN_KILL_COLOR, tol=0.2):
                    found_fireball = True
        if found_fireball:
            break
    assert found_fireball, "No fireball cells observed after alien kill"


def test_defender_shots_in_bounds():
    """All cells produced during ACTIVE phase have valid coordinates."""
    effect = InvadersEffect(seed=3, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    run_to_phase(effect, Phase.ACTIVE, max_ticks=500)
    for _ in range(200):
        for out in effect.tick():
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 80, f"Cell x={x} OOB"
                assert 0 <= y < 24, f"Cell y={y} OOB"
        if effect.phase != Phase.ACTIVE:
            break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_approx_color(fg, reference, tol=0.05):
    """Check if fg approximately matches reference color (ignoring alpha)."""
    return all(abs(fg[i] - reference[i]) <= tol for i in range(3))


def _is_approx_any_alien_color(fg, tol=0.15):
    """Check if fg approximately matches any of the ALIEN_COLORS."""
    return any(
        all(abs(fg[i] - ref[i]) <= tol for i in range(3))
        for ref in ALIEN_COLORS
    )
