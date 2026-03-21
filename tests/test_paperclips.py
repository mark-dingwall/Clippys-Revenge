"""Tests for clippy.effects.paperclips — PaperclipsEffect."""
import json
import math

import pytest

from clippy.effects.paperclips import (
    CLIP_COLORS,
    COUNTER_BG,
    COUNTER_FG,
    EARTH_TRANSITION_DURATION,
    FADE_DURATION,
    FLASH_DURATION,
    GROWTH_DOUBLING_TICKS,
    SEEDING_DURATION,
    TARGET_PAPERCLIPS,
    TIER0_TEMPLATES,
    PaperclipsEffect,
    Phase,
)
from clippy.harness import step
from clippy.types import Cell, OutputCells, PTYUpdate, TTYResize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pty_cells(width=80, height=24, density=0.5, seed=0):
    """Generate a list of Cell objects simulating terminal content."""
    import random
    rng = random.Random(seed)
    chars = list("abcdefghijklmnopqrstuvwxyz0123456789{}[]()=+-*/;:.'\"")
    cells = []
    for y in range(height):
        for x in range(width):
            if rng.random() < density:
                ch = rng.choice(chars)
                cells.append(Cell(
                    character=ch,
                    coordinates=(x, y),
                    fg=(1.0, 1.0, 1.0, 1.0),
                    bg=None,
                ))
    return cells


def make_pty_update(width=80, height=24, density=0.5, seed=0):
    cells = _make_pty_cells(width, height, density, seed)
    return PTYUpdate(size=(width, height), cells=cells, cursor=(0, 0))


def make_pty_json(width=80, height=24, density=0.5, seed=0):
    cells = _make_pty_cells(width, height, density, seed)
    return json.dumps({
        "pty_update": {
            "size": [width, height],
            "cells": [
                {
                    "character": c.character,
                    "coordinates": list(c.coordinates),
                    "fg": list(c.fg) if c.fg else None,
                    "bg": list(c.bg) if c.bg else None,
                }
                for c in cells
            ],
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
    effect = PaperclipsEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=seed))
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
    effect = PaperclipsEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=seed))
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
    effect = PaperclipsEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=seed))
    for _ in range(200):
        for out in effect.tick():
            assert isinstance(out, OutputCells)


@pytest.mark.parametrize("seed", SEEDS)
def test_liveness(seed):
    """Non-empty output within 40 ticks of PTYUpdate."""
    effect = PaperclipsEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=seed))
    found_output = False
    for _ in range(40):
        outputs = effect.tick()
        for out in outputs:
            if isinstance(out, OutputCells) and out.cells:
                found_output = True
                break
        if found_output:
            break
    assert found_output, "No output in first 40 ticks"


@pytest.mark.parametrize("seed", SEEDS)
def test_eventual_completion(seed):
    """Effect reaches DONE within 8000 ticks on a small terminal."""
    effect = PaperclipsEffect(seed=seed, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=seed))
    reached_done = run_to_phase(effect, Phase.DONE, max_ticks=8000)
    assert reached_done, (
        f"Effect did not reach DONE in 8000 ticks, stuck at {effect.phase.name}"
    )


# ---------------------------------------------------------------------------
# Phase / lifecycle tests
# ---------------------------------------------------------------------------

def test_idle_returns_empty():
    """tick() returns [] before any PTYUpdate."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    assert effect.tick() == []
    assert effect.phase == Phase.IDLE


def test_seeding_after_pty_update():
    """Phase is SEEDING after PTYUpdate + first tick."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    effect.tick()
    assert effect.phase == Phase.SEEDING


def test_replicating_starts_after_seeding():
    """Phase transitions to REPLICATING after SEEDING_DURATION ticks."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    advance(effect, SEEDING_DURATION + 2)
    assert effect.phase == Phase.REPLICATING


def test_phases_never_decrease():
    """Phase value never decreases during a single lifecycle."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=42))
    prev_phase = effect.phase
    for _ in range(15000):
        effect.tick()
        current = effect.phase
        assert current >= prev_phase, (
            f"Phase regressed from {Phase(prev_phase).name} to {Phase(current).name}"
        )
        prev_phase = current
        if current == Phase.DONE:
            break


def test_done_returns_empty():
    """tick() returns [] after reaching DONE."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=42))
    assert run_to_phase(effect, Phase.DONE, max_ticks=8000)
    assert effect.tick() == []
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_consumed_positions_grow():
    """Consumed positions monotonically increase during REPLICATING."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12, density=0.4, seed=0))
    # Advance to REPLICATING
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    prev_count = len(effect._consumed)
    grew = False
    for _ in range(100):
        effect.tick()
        cur = len(effect._consumed)
        assert cur >= prev_count, "Consumed positions decreased"
        if cur > prev_count:
            grew = True
        prev_count = cur
        if effect.phase != Phase.REPLICATING:
            break
    assert grew, "Consumed positions never grew during REPLICATING"


def test_exponential_growth():
    """Clips grow over time during REPLICATING (wave speed accelerates)."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.6, seed=0))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    advance(effect, 30)
    clips_at_30 = effect._total_clips
    advance(effect, 30)
    clips_at_60 = effect._total_clips
    assert clips_at_60 > clips_at_30, (
        f"Clips did not grow: tick 30={clips_at_30}, tick 60={clips_at_60}"
    )


def test_counter_matches_total_clips():
    """Counter text reflects _total_clips (or _display_count)."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=0))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    advance(effect, 30)
    label = effect._counter_label()
    assert str(effect._display_count) in label or effect._format_count(effect._display_count) in label


def test_flash_cells_expire():
    """Flash cells are pruned after FLASH_DURATION ticks."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.5, seed=0))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    # Run enough ticks to generate flashes
    advance(effect, 10)
    if effect._flash_cells:
        oldest_born = min(fi.born_tick for fi in effect._flash_cells.values())
        # Advance past flash duration
        ticks_needed = FLASH_DURATION + 2 - (effect._tick_count - oldest_born)
        if ticks_needed > 0:
            advance(effect, ticks_needed)
        # All flashes from that batch should be pruned
        for fi in effect._flash_cells.values():
            age = effect._tick_count - fi.born_tick
            assert age < FLASH_DURATION, f"Flash not pruned: age={age}"


# ---------------------------------------------------------------------------
# Cursor-shake cancellation
# ---------------------------------------------------------------------------

def test_cancel_during_replicating():
    """cancel() during REPLICATING transitions to FADING."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=0))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)

    effect.cancel()
    assert effect.phase == Phase.FADING, (
        f"Expected FADING after cancel(), got {effect.phase.name}"
    )


def test_cancel_during_seeding():
    """cancel() during SEEDING transitions to FADING."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=0))
    effect.tick()  # enters SEEDING
    assert effect.phase == Phase.SEEDING

    effect.cancel()
    assert effect.phase == Phase.FADING


def test_cancel_during_earth_phases():
    """cancel() during EARTH_REPLICATING transitions to FADING."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    assert run_to_phase(effect, Phase.EARTH_REPLICATING, max_ticks=10000)

    effect.cancel()
    assert effect.phase == Phase.FADING


def test_is_done_property():
    """is_done is True iff phase is DONE."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    assert not effect.is_done
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=42))
    run_to_phase(effect, Phase.DONE, max_ticks=8000)
    assert effect.is_done


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def test_resize_no_oob():
    """No out-of-bounds coordinates after shrinking the terminal."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12, density=0.4, seed=42))
    advance(effect, SEEDING_DURATION + 20)

    effect.on_resize(TTYResize(width=20, height=6))
    for _ in range(20):
        for out in effect.tick():
            for cell in out.cells:
                x, y = cell.coordinates
                assert 0 <= x < 20, f"x={x} OOB after resize"
                assert 0 <= y < 6, f"y={y} OOB after resize"


def test_resize_prunes_clip_cells():
    """Clip cells outside new bounds are dropped after resize."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=42))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    advance(effect, 30)

    effect.on_resize(TTYResize(width=20, height=6))
    for pos in effect._clip_cells:
        assert 0 <= pos[0] < 20, f"Clip x={pos[0]} not pruned"
        assert 0 <= pos[1] < 6, f"Clip y={pos[1]} not pruned"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_seeded_deterministic():
    """Same seed produces identical first 5 frames."""
    def collect_frames(seed):
        effect = PaperclipsEffect(seed=seed, idle_secs=0)
        effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=seed))
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
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_terminal():
    """Empty terminal (no PTY content) still works without errors."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(PTYUpdate(size=(80, 24), cells=[], cursor=(0, 0)))
    for _ in range(8000):
        effect.tick()
        if effect.phase == Phase.DONE:
            break
    assert effect.phase in (Phase.DONE, Phase.IDLE)


def test_tiny_terminal():
    """Tiny terminal (5x3) only uses single-char clips, no crashes."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    cells = [
        Cell(character="x", coordinates=(x, y), fg=(1.0, 1.0, 1.0, 1.0), bg=None)
        for x in range(5) for y in range(3)
    ]
    effect.on_pty_update(PTYUpdate(size=(5, 3), cells=cells, cursor=(0, 0)))
    for _ in range(500):
        outputs = effect.tick()
        for out in outputs:
            if isinstance(out, OutputCells):
                for cell in out.cells:
                    x, y = cell.coordinates
                    assert 0 <= x < 5, f"x={x} OOB on tiny terminal"
                    assert 0 <= y < 3, f"y={y} OOB on tiny terminal"
        if effect.phase == Phase.DONE:
            break


# ---------------------------------------------------------------------------
# Counter formatting
# ---------------------------------------------------------------------------

def test_format_count_units():
    """Counter formatting uses correct SI suffixes."""
    effect = PaperclipsEffect(seed=0)
    assert effect._format_count(0) == "0"
    assert effect._format_count(1) == "1"
    assert effect._format_count(999) == "999"
    assert "K" in effect._format_count(1_500)
    assert "M" in effect._format_count(2_500_000)
    assert "B" in effect._format_count(3_000_000_000)
    assert "T" in effect._format_count(1_000_000_000_000)
    assert "Q" in effect._format_count(1_000_000_000_000_000)
    assert "Qi" in effect._format_count(1_000_000_000_000_000_000)
    assert "Sx" in effect._format_count(1_000_000_000_000_000_000_000)
    assert "Sp" in effect._format_count(1_000_000_000_000_000_000_000_000)
    assert "Oc" in effect._format_count(1_000_000_000_000_000_000_000_000_000)


# ---------------------------------------------------------------------------
# Fading
# ---------------------------------------------------------------------------

def test_fading_alpha_decreases():
    """Once FADING, cells have alpha < 1.0; eventually transitions to DONE."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    reached_fading = run_to_phase(effect, Phase.FADING, max_ticks=8000)
    assert reached_fading, "Never reached FADING"

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


# ---------------------------------------------------------------------------
# Harness integration
# ---------------------------------------------------------------------------

def test_step_integration():
    """harness.step() returns output_cells as a direct array (not nested object)."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)

    result = step(effect, [make_pty_json(80, 24, density=0.4, seed=0)])
    for _ in range(SEEDING_DURATION + 10):
        more = step(effect, [])
        result.extend(more)

    assert len(result) >= 1
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
# Template tier selection
# ---------------------------------------------------------------------------

def test_tier_upgrade_with_clip_count():
    """Larger templates become available as total_clips increases."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    # With 0 clips, only tier 0 is eligible
    effect._total_clips = 0
    tiers = effect._eligible_tiers()
    assert len(tiers) == 1  # only tier 0

    effect._total_clips = 5
    tiers = effect._eligible_tiers()
    assert len(tiers) == 2  # tier 0 + tier 1

    effect._total_clips = 20
    tiers = effect._eligible_tiers()
    assert len(tiers) == 3  # tier 0 + tier 1 + tier 2

    effect._total_clips = 60
    tiers = effect._eligible_tiers()
    assert len(tiers) == 4  # all tiers

    # _all_tiers_unlocked overrides thresholds
    effect._total_clips = 0
    effect._all_tiers_unlocked = True
    tiers = effect._eligible_tiers()
    assert len(tiers) == 4  # all tiers regardless of count


# ---------------------------------------------------------------------------
# Wave propagation tests
# ---------------------------------------------------------------------------

def test_wave_spatial_ordering():
    """First clips placed are near the wave origin."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12, density=0.5, seed=42))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    # Run a few ticks to place some clips via the wave
    advance(effect, 10)
    ox, oy = effect._wave_origin
    max_dist = 0.0
    for pos in effect._clip_cells:
        dist = math.hypot(pos[0] - ox, (pos[1] - oy) * 2.0)
        if dist > max_dist:
            max_dist = dist
    # All clips should be within the wave radius (+ template spread tolerance)
    assert max_dist <= effect._wave_radius + 5, (
        f"Clip at distance {max_dist:.1f} exceeds wave radius {effect._wave_radius:.1f}"
    )


def test_mixed_tier_sizes():
    """Multiple tier sizes are present after enough clips are placed."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.5, seed=42))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    advance(effect, 120)
    # Collect clip characters — tier 0 uses ∂/§, tier 1+ uses box-drawing
    chars = {cc.ch for cc in effect._clip_cells.values()}
    tier0_chars = {t[0][2] for t in TIER0_TEMPLATES}
    has_tier0 = bool(chars & tier0_chars)
    has_other = bool(chars - tier0_chars - {" "})
    assert has_tier0 and has_other, (
        f"Expected mix of tier sizes, got chars: {chars}"
    )


# ---------------------------------------------------------------------------
# Filling phase tests
# ---------------------------------------------------------------------------

def test_filling_phase_reached():
    """Effect enters FILLING after text positions are consumed."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    reached = run_to_phase(effect, Phase.FILLING, max_ticks=3000)
    assert reached, f"Never reached FILLING, stuck at {effect.phase.name}"


def test_screen_full_before_earth():
    """Nearly all positions have clips before EARTH_TRANSITION."""
    w, h = 20, 8
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(w, h, density=0.3, seed=0))
    last_filling_clip_count = 0
    for _ in range(8000):
        if effect.phase == Phase.FILLING:
            last_filling_clip_count = len(effect._clip_cells)
        effect.tick()
        if effect.phase == Phase.EARTH_TRANSITION:
            break
    assert effect.phase == Phase.EARTH_TRANSITION, (
        f"Never reached EARTH_TRANSITION, stuck at {effect.phase.name}"
    )
    total = w * h
    coverage = last_filling_clip_count / total
    assert coverage > 0.8, f"Only {coverage:.1%} coverage before earth phase"


# ---------------------------------------------------------------------------
# Earth phase tests
# ---------------------------------------------------------------------------

def test_earth_transition_clears_clips():
    """clip_cells are cleared when entering EARTH_TRANSITION."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    assert run_to_phase(effect, Phase.EARTH_TRANSITION, max_ticks=8000)
    assert len(effect._clip_cells) == 0, "Clips should be cleared at EARTH_TRANSITION"


def test_earth_all_tiers_unlocked():
    """All tiers are eligible during EARTH_REPLICATING."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    assert run_to_phase(effect, Phase.EARTH_REPLICATING, max_ticks=10000)
    assert effect._all_tiers_unlocked
    tiers = effect._eligible_tiers()
    assert len(tiers) == 4, f"Expected 4 tiers, got {len(tiers)}"


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------

def test_full_lifecycle():
    """Effect visits all phases from IDLE to DONE."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=42))
    phases_seen = {effect.phase}
    for _ in range(15000):
        effect.tick()
        phases_seen.add(effect.phase)
        if effect.phase == Phase.DONE:
            break
    expected = {
        Phase.IDLE, Phase.SEEDING, Phase.REPLICATING, Phase.FILLING,
        Phase.EARTH_TRANSITION, Phase.EARTH_REPLICATING,
        Phase.FADING, Phase.DONE,
    }
    missing = expected - phases_seen
    assert not missing, f"Missing phases: {[p.name for p in missing]}"


# ---------------------------------------------------------------------------
# Counter acceleration
# ---------------------------------------------------------------------------

def test_counter_reaches_target():
    """After EARTH_REPLICATING, display_count >= TARGET_PAPERCLIPS."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(20, 8, density=0.3, seed=0))
    assert run_to_phase(effect, Phase.FADING, max_ticks=15000)
    assert effect._display_count >= TARGET_PAPERCLIPS, (
        f"Counter only reached {effect._display_count}"
    )


# ---------------------------------------------------------------------------
# Wave origin / stars / solid wave tests
# ---------------------------------------------------------------------------

def test_wave_origin_from_terminal_content():
    """Wave origin is at a PTY cell position after _start_effect()."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24, density=0.4, seed=42))
    effect.tick()  # enters SEEDING → _start_effect was called
    origin = (int(effect._wave_origin[0]), int(effect._wave_origin[1]))
    assert origin in effect._pty_cells, (
        f"Wave origin {origin} not in PTY cells"
    )


def test_stars_in_earth_phase():
    """Stars are generated for earth phase, with Chebyshev distance >= 3 from earth."""
    effect = PaperclipsEffect(seed=0, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 50, density=0.3, seed=0))
    assert run_to_phase(effect, Phase.EARTH_TRANSITION, max_ticks=8000)
    assert effect._star_cells, "No stars generated"
    for (sx, sy) in effect._star_cells:
        for (ex, ey) in effect._earth_cells:
            dist = max(abs(sx - ex), abs(sy - ey))
            assert dist >= 3, (
                f"Star at ({sx},{sy}) too close to earth at ({ex},{ey}): dist={dist}"
            )


def test_solid_wave_front():
    """All positions within wave radius are consumed (no gaps) during REPLICATING."""
    effect = PaperclipsEffect(seed=42, idle_secs=0)
    effect.on_pty_update(make_pty_update(40, 12, density=0.5, seed=42))
    assert run_to_phase(effect, Phase.REPLICATING, max_ticks=100)
    advance(effect, 20)
    ox, oy = effect._wave_origin
    # Check: every PTY position within the wave radius should be consumed
    for pos in effect._pty_cells:
        dist = math.hypot(pos[0] - ox, (pos[1] - oy) * 2.0)
        # Allow small tolerance for wave radius boundary
        if dist <= effect._wave_radius - 1.0:
            assert pos in effect._consumed or pos in effect._counter_positions, (
                f"Position {pos} at dist {dist:.1f} not consumed (radius={effect._wave_radius:.1f})"
            )
