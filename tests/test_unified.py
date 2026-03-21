"""Tests for clippy.unified — UnifiedEffect state machine."""
from __future__ import annotations

import json

import pytest

from clippy.effects.fire import FireEffect
from clippy.unified import (
    BLINK_DURATION,
    CACKLE_FLIP_TICKS,
    FACE_H,
    FACE_W,
    FPS,
    MARGIN,
    UnifiedEffect,
    UnifiedPhase,
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


# A minimal fake effect for fast testing
class FakeEffect:
    EFFECT_META = {"name": "fake", "description": "test effect"}

    def __init__(self, seed=None, idle_secs=None):
        self._done = False
        self._cancelled = False
        self._tick_count = 0
        self._received_update = False

    def on_pty_update(self, update):
        self._received_update = True

    def on_resize(self, resize):
        pass

    def tick(self):
        self._tick_count += 1
        if self._cancelled:
            if self._tick_count > 3:  # fade out after 3 ticks
                self._done = True
            return [OutputCells(cells=[])]
        if self._tick_count > 20:
            self._done = True
        return [OutputCells(cells=[])]

    def cancel(self):
        self._cancelled = True

    @property
    def is_done(self):
        return self._done


# ---------------------------------------------------------------------------
# Demo mode lifecycle
# ---------------------------------------------------------------------------

def test_demo_starts_at_active():
    """Demo mode (idle_secs=0) starts directly at ACTIVE."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE


def test_demo_full_lifecycle():
    """Demo: ACTIVE → DONE (no IMMINENT_DEEP or CACKLING)."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE

    # Inner effect completes after ~20 ticks → straight to DONE
    assert run_to_phase(effect, UnifiedPhase.DONE, max_ticks=50)
    assert effect.phase == UnifiedPhase.DONE
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Live mode lifecycle
# ---------------------------------------------------------------------------

def test_live_mode_loops():
    """Live mode loops back to WATCHING after CACKLING."""
    idle_secs = 15
    effect = UnifiedEffect(FakeEffect, idle_secs=idle_secs, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.WATCHING

    # Full cycle: WATCHING → IMMINENT_EARLY → IMMINENT_DEEP → ACTIVE → CACKLING → WATCHING
    total_ticks = round(idle_secs * FPS) + 200
    saw_cackling = False
    for _ in range(total_ticks):
        effect.tick()
        if effect.phase == UnifiedPhase.CACKLING:
            saw_cackling = True
        if saw_cackling and effect.phase == UnifiedPhase.WATCHING:
            break

    assert effect.phase == UnifiedPhase.WATCHING, (
        f"Expected WATCHING after loop, got {effect.phase.name}"
    )


def test_live_timing_imminent_early():
    """IMMINENT_EARLY starts at idle_secs - 10 (adjusted for BLINK_DURATION init offset)."""
    idle_secs = 15
    effect = UnifiedEffect(FakeEffect, idle_secs=idle_secs, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))

    # _tick_count starts at BLINK_DURATION (3), so we need fewer ticks
    target_tick = round((idle_secs - 10) * FPS)
    ticks_needed = target_tick - BLINK_DURATION - 1
    advance(effect, ticks_needed)
    assert effect.phase == UnifiedPhase.WATCHING

    effect.tick()
    assert effect.phase == UnifiedPhase.IMMINENT_EARLY


def test_live_timing_imminent_deep():
    """IMMINENT_DEEP starts at idle_secs - 5 (adjusted for BLINK_DURATION init offset)."""
    idle_secs = 15
    effect = UnifiedEffect(FakeEffect, idle_secs=idle_secs, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))

    target_tick = round((idle_secs - 5) * FPS)
    ticks_needed = target_tick - BLINK_DURATION - 1
    advance(effect, ticks_needed)
    assert effect.phase in (UnifiedPhase.WATCHING, UnifiedPhase.IMMINENT_EARLY)

    effect.tick()
    assert effect.phase == UnifiedPhase.IMMINENT_DEEP


# ---------------------------------------------------------------------------
# L+R shake detection
# ---------------------------------------------------------------------------

def _shake_msgs():
    return [make_pty_json(cursor=(x, 0)) for x in [10, 30, 10, 30, 10, 30, 10]]


def test_shake_during_watching_jumps_to_imminent_deep():
    """L+R during WATCHING jumps to IMMINENT_DEEP."""
    effect = UnifiedEffect(FakeEffect, idle_secs=300, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(5):
        effect.tick()
    assert effect.phase == UnifiedPhase.WATCHING

    step(effect, _shake_msgs())
    assert effect.phase == UnifiedPhase.IMMINENT_DEEP


def test_shake_during_watching_resets_counter():
    """After shake in WATCHING, detector is reset (no carryover)."""
    effect = UnifiedEffect(FakeEffect, idle_secs=300, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    for _ in range(5):
        effect.tick()

    step(effect, _shake_msgs())
    assert effect.phase == UnifiedPhase.IMMINENT_DEEP
    assert effect._shake._reversal_ticks == []
    assert effect._shake._last_x is None


def test_shake_during_active_cancels_inner_effect():
    """L+R during ACTIVE calls cancel() on inner effect."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE
    assert effect._inner is not None
    assert not effect._inner._cancelled

    # Shake during ACTIVE
    for msg in _shake_msgs():
        from clippy.types import from_json
        parsed = from_json(msg)
        if parsed is not None:
            effect.on_pty_update(parsed)

    assert effect._inner._cancelled


def test_shake_ignored_during_imminent_early():
    """L+R during IMMINENT_EARLY does NOT accumulate reversals."""
    effect = UnifiedEffect(FakeEffect, idle_secs=15, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, UnifiedPhase.IMMINENT_EARLY, max_ticks=round(6 * FPS))
    assert effect.phase == UnifiedPhase.IMMINENT_EARLY

    # Send shake messages — should be completely ignored
    step(effect, _shake_msgs())
    # Phase should still be IMMINENT_EARLY (or IMMINENT_DEEP if timer advanced)
    assert effect.phase in (UnifiedPhase.IMMINENT_EARLY, UnifiedPhase.IMMINENT_DEEP)
    # Detector should not have accumulated anything
    assert effect._shake._reversal_ticks == []


def test_shake_ignored_during_cackling():
    """L+R during CACKLING does NOT accumulate reversals."""
    effect = UnifiedEffect(FakeEffect, idle_secs=15, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, UnifiedPhase.CACKLING, max_ticks=round(16 * FPS))

    step(effect, _shake_msgs())
    assert effect._shake._reversal_ticks == []


def test_counter_resets_on_active_entry():
    """Shake counter resets when entering ACTIVE."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE
    # Shake state should be clean on ACTIVE entry
    assert effect._shake._reversal_ticks == []


# ---------------------------------------------------------------------------
# Mascot rendering
# ---------------------------------------------------------------------------

def test_mascot_renders_during_active():
    """Mascot cells are present in output during ACTIVE phase."""
    w, h = 80, 24
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(w, h))
    assert effect.phase == UnifiedPhase.ACTIVE

    corner_x = w - FACE_W - MARGIN
    outputs = effect.tick()
    cells = cells_from_outputs(outputs)
    mascot_cells = [c for c in cells if c.coordinates[0] >= corner_x]
    assert len(mascot_cells) > 0, "No mascot cells during ACTIVE"


def test_mascot_merged_into_single_output_cells():
    """During ACTIVE, mascot cells are merged into the inner effect's OutputCells,
    not emitted as a separate message (tattoy would overwrite the effect layer)."""
    w, h = 80, 24
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(w, h))
    assert effect.phase == UnifiedPhase.ACTIVE

    outputs = effect.tick()
    # FakeEffect emits one OutputCells; mascot should be merged into it
    output_cells_count = sum(1 for o in outputs if isinstance(o, OutputCells))
    assert output_cells_count == 1, (
        f"Expected 1 OutputCells message (merged), got {output_cells_count}"
    )


def test_mascot_separate_from_pixel_effect():
    """When inner effect uses OutputPixels, mascot emits separate OutputCells
    (different wire types don't conflict in tattoy)."""
    from clippy.types import OutputPixels, Pixel

    class PixelEffect:
        EFFECT_META = {"name": "pixel_fake", "description": "test"}
        def __init__(self, seed=None, idle_secs=None):
            self._tick = 0
        def on_pty_update(self, update): pass
        def on_resize(self, resize): pass
        def tick(self):
            self._tick += 1
            return [OutputPixels(pixels=[Pixel(coordinates=(0, 0), color=(1.0, 0.0, 0.0, 1.0))])]
        def cancel(self): pass
        @property
        def is_done(self):
            return self._tick > 20

    w, h = 80, 24
    effect = UnifiedEffect(PixelEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(w, h))
    assert effect.phase == UnifiedPhase.ACTIVE

    outputs = effect.tick()
    types = [type(o).__name__ for o in outputs]
    assert "OutputPixels" in types, "Inner effect's OutputPixels missing"
    assert "OutputCells" in types, "Mascot's OutputCells missing"


def test_cackling_alternates_frames():
    """CACKLING alternates body frame chars (live mode)."""
    w, h = 80, 24
    effect = UnifiedEffect(FakeEffect, idle_secs=15, seed=42)
    effect.on_pty_update(make_pty_update(w, h))
    assert run_to_phase(effect, UnifiedPhase.CACKLING, max_ticks=round(16 * FPS))

    corner_x = w - FACE_W - MARGIN
    corner_y = h - FACE_H - MARGIN
    top_left = (corner_x, corner_y)

    chars = set()
    for _ in range(CACKLE_FLIP_TICKS * 4):
        outputs = effect.tick()
        ch = char_at(outputs, top_left)
        if ch is not None:
            chars.add(ch)

    assert "╭" in chars and "╔" in chars, f"Expected alternating frames, got: {chars}"


# ---------------------------------------------------------------------------
# Inner effect lifecycle
# ---------------------------------------------------------------------------

def test_inner_effect_receives_pty_update():
    """Inner effect gets on_pty_update when created."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE
    assert effect._inner is not None
    assert effect._inner._received_update


def test_inner_effect_natural_completion_goes_to_done_in_demo():
    """When inner effect is_done in demo mode, transitions straight to DONE."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE

    # FakeEffect completes after 20 ticks
    assert run_to_phase(effect, UnifiedPhase.DONE, max_ticks=50)


def test_inner_effect_natural_completion_triggers_cackling_in_live():
    """When inner effect is_done in live mode, transitions to CACKLING."""
    effect = UnifiedEffect(FakeEffect, idle_secs=15, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert run_to_phase(effect, UnifiedPhase.ACTIVE, max_ticks=round(16 * FPS))

    # FakeEffect completes after 20 ticks
    assert run_to_phase(effect, UnifiedPhase.CACKLING, max_ticks=50)
    assert effect._inner is None  # cleared on CACKLING entry


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------

def test_resize_forwarded_during_active():
    """on_resize forwarded to inner effect during ACTIVE."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE

    effect.on_resize(TTYResize(width=40, height=12))
    assert effect._width == 40
    assert effect._height == 12


# ---------------------------------------------------------------------------
# Small terminal
# ---------------------------------------------------------------------------

def test_small_terminal_no_mascot():
    """Terminal too small for mascot produces empty mascot output."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(3, 3))
    outputs = effect.tick()
    # Should not crash; mascot skipped due to small terminal
    cells = cells_from_outputs(outputs)
    assert len(cells) == 0


# ---------------------------------------------------------------------------
# No output before first update
# ---------------------------------------------------------------------------

def test_no_output_before_pty_update():
    """tick() returns [] before any PTYUpdate."""
    effect = UnifiedEffect(FakeEffect, idle_secs=300)
    assert effect.tick() == []


# ---------------------------------------------------------------------------
# Integration with real effects
# ---------------------------------------------------------------------------

def test_with_fire_effect_demo():
    """UnifiedEffect wrapping FireEffect completes demo lifecycle."""
    effect = UnifiedEffect(FireEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(20, 8))

    phases_seen = {effect.phase}
    for _ in range(3000):
        effect.tick()
        phases_seen.add(effect.phase)
        if effect.phase == UnifiedPhase.DONE:
            break

    assert UnifiedPhase.ACTIVE in phases_seen, "Never entered ACTIVE phase"
    assert effect.phase == UnifiedPhase.DONE, (
        f"Expected DONE, got {effect.phase.name}"
    )


# ---------------------------------------------------------------------------
# Effect cycling
# ---------------------------------------------------------------------------

class _TaggedEffect:
    """Factory for distinguishable fake effect classes."""
    @staticmethod
    def make(tag: str):
        class Tagged(FakeEffect):
            EFFECT_META = {"name": tag, "description": f"tagged {tag}"}
            effect_tag = tag
        Tagged.__name__ = f"Tagged_{tag}"
        Tagged.__qualname__ = f"Tagged_{tag}"
        return Tagged


EffectA = _TaggedEffect.make("A")
EffectB = _TaggedEffect.make("B")
EffectC = _TaggedEffect.make("C")


def test_cycles_through_all_effects():
    """With 3 effect classes, each cycle contains all 3."""
    effect2 = UnifiedEffect([EffectA, EffectB, EffectC], idle_secs=15, seed=42)
    effect2.on_pty_update(make_pty_update(80, 24))

    tags_seen = []
    for _ in range(3):
        assert run_to_phase(effect2, UnifiedPhase.ACTIVE, max_ticks=round(16 * FPS))
        tags_seen.append(effect2._inner.effect_tag)
        assert run_to_phase(effect2, UnifiedPhase.CACKLING, max_ticks=50)
        # Continue to next WATCHING
        assert run_to_phase(effect2, UnifiedPhase.WATCHING, max_ticks=round(6 * FPS))

    assert sorted(tags_seen) == ["A", "B", "C"], f"Expected all 3 effects, got {tags_seen}"


def test_no_repeat_across_shuffle_boundary():
    """Last effect of cycle N != first of cycle N+1."""
    effect = UnifiedEffect([EffectA, EffectB, EffectC], idle_secs=15, seed=99)
    effect.on_pty_update(make_pty_update(80, 24))

    tags = []
    for _ in range(6):  # Two full cycles
        assert run_to_phase(effect, UnifiedPhase.ACTIVE, max_ticks=round(16 * FPS))
        tags.append(effect._inner.effect_tag)
        assert run_to_phase(effect, UnifiedPhase.CACKLING, max_ticks=50)
        assert run_to_phase(effect, UnifiedPhase.WATCHING, max_ticks=round(6 * FPS))

    # At the boundary (index 2→3), they should differ
    assert tags[2] != tags[3], f"Repeat across shuffle boundary: {tags}"


def test_single_class_list_repeats():
    """A list with one effect class repeats without crashing."""
    effect = UnifiedEffect([FakeEffect], idle_secs=15, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))

    for _ in range(3):
        assert run_to_phase(effect, UnifiedPhase.ACTIVE, max_ticks=round(16 * FPS))
        assert effect._inner is not None
        assert run_to_phase(effect, UnifiedPhase.CACKLING, max_ticks=50)
        assert run_to_phase(effect, UnifiedPhase.WATCHING, max_ticks=round(6 * FPS))


def test_single_class_not_list_backward_compat():
    """Passing a bare class (not a list) still works."""
    effect = UnifiedEffect(FakeEffect, idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))
    assert effect.phase == UnifiedPhase.ACTIVE
    assert effect._inner is not None
    assert run_to_phase(effect, UnifiedPhase.DONE, max_ticks=300)


def test_demo_mode_single_effect_no_cycling():
    """Demo mode plays one effect then exits, even with multiple classes."""
    effect = UnifiedEffect([EffectA, EffectB, EffectC], idle_secs=0, seed=42)
    effect.on_pty_update(make_pty_update(80, 24))

    assert run_to_phase(effect, UnifiedPhase.DONE, max_ticks=500)
    assert effect.phase == UnifiedPhase.DONE
