"""Unified effect — single state machine wrapping an inner effect + mascot overlay."""
from __future__ import annotations

import os
import random
from enum import IntEnum

from clippy.harness import Effect
from clippy.mascot_render import (
    BLINK_DURATION,
    CACKLE_FLIP_TICKS,
    FACE_H,
    FACE_W,
    MARGIN,
    render_mascot,
)
from clippy.types import (
    Cell,
    CursorShakeDetector,
    OutputCells,
    OutputMessage,
    PTYUpdate,
    TTYResize,
)

FPS = 30


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class UnifiedPhase(IntEnum):
    WATCHING = 0
    IMMINENT_EARLY = 1
    IMMINENT_DEEP = 2
    ACTIVE = 3
    CACKLING = 4
    DONE = 5


# ---------------------------------------------------------------------------
# UnifiedEffect
# ---------------------------------------------------------------------------

class UnifiedEffect:
    EFFECT_META = {
        "name": "unified",
        "description": "Unified lifecycle: mascot + inner effect",
    }

    def __init__(
        self,
        effect_classes,
        *,
        seed: int | None = None,
        idle_secs: float | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        # Normalize: accept single class or list
        if isinstance(effect_classes, list):
            self._effect_classes = list(effect_classes)
        else:
            self._effect_classes = [effect_classes]
        self._effect_queue: list = []
        self._last_played = None  # anti-repeat across shuffle boundaries
        self._advance_queue()
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._demo_mode = idle_secs == 0
        self._phase = UnifiedPhase.WATCHING
        self._shake = CursorShakeDetector()
        self._inner: Effect | None = None
        self._tick_count = BLINK_DURATION  # match mascot init
        self._width = 0
        self._height = 0
        self._received_first_update = False

        # Last PTYUpdate for forwarding to inner effect on creation
        self._last_pty_update: PTYUpdate | None = None

        # Timing
        self._imminent_early_start = 0
        self._imminent_deep_start = 0
        self._effect_start = 0
        self._cackle_start = 0
        self._cackle_end = 0

    # -- Timing -----------------------------------------------------------

    def _compute_timing(self) -> None:
        if self._demo_mode:
            # Demo: skip straight to ACTIVE (no IMMINENT_DEEP / CACKLING)
            self._imminent_early_start = 0
            self._imminent_deep_start = 0
            self._effect_start = 0
        else:
            total = round(self._idle_secs * FPS)
            self._imminent_early_start = total - round(10 * FPS)
            self._imminent_deep_start = total - round(5 * FPS)
            self._effect_start = total
            # cackle_start/end set when entering CACKLING

    # -- Protocol callbacks -----------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        self._width, self._height = update.size
        self._last_pty_update = update

        # Forward to inner effect during ACTIVE
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.on_pty_update(update)

        # L+R only during WATCHING and ACTIVE
        if self._phase == UnifiedPhase.WATCHING:
            if self._shake.update(update.cursor):
                self._phase = UnifiedPhase.IMMINENT_DEEP
                self._effect_start = self._tick_count + round(5 * FPS)
                self._shake.reset()
        elif self._phase == UnifiedPhase.ACTIVE:
            if self._shake.update(update.cursor):
                if self._inner is not None:
                    self._inner.cancel()
                self._shake.reset()
        # All other phases: don't call _shake.update() at all

        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()
            if self._demo_mode:
                self._start_inner_effect()

    def on_resize(self, resize: TTYResize) -> None:
        self._width, self._height = resize.width, resize.height
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.on_resize(resize)
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()
            if self._demo_mode:
                self._start_inner_effect()

    # -- Phase transitions ------------------------------------------------

    @property
    def phase(self) -> UnifiedPhase:
        return self._phase

    def cancel(self) -> None:
        if self._inner is not None and self._phase == UnifiedPhase.ACTIVE:
            self._inner.cancel()
        if self._phase != UnifiedPhase.DONE:
            self._phase = UnifiedPhase.DONE
            self._inner = None

    @property
    def is_done(self) -> bool:
        return self._phase == UnifiedPhase.DONE

    def _update_phase(self) -> None:
        t = self._tick_count
        if self._phase == UnifiedPhase.WATCHING and t >= self._imminent_early_start:
            self._phase = UnifiedPhase.IMMINENT_EARLY
        elif self._phase == UnifiedPhase.IMMINENT_EARLY and t >= self._imminent_deep_start:
            self._phase = UnifiedPhase.IMMINENT_DEEP
        elif self._phase == UnifiedPhase.IMMINENT_DEEP and t >= self._effect_start:
            self._start_inner_effect()

    def _advance_queue(self) -> None:
        """Shuffle all effect classes into the queue, with anti-repeat."""
        self._effect_queue = list(self._effect_classes)
        self._rng.shuffle(self._effect_queue)
        # If first item matches last played, rotate it to the end
        if (len(self._effect_queue) > 1
                and self._effect_queue[0] is self._last_played):
            self._effect_queue.append(self._effect_queue.pop(0))

    def _next_effect_class(self):
        """Pop the next effect class from the queue, refilling when empty."""
        if not self._effect_queue:
            self._advance_queue()
        return self._effect_queue.pop(0)

    def _start_inner_effect(self) -> None:
        self._phase = UnifiedPhase.ACTIVE
        inner_seed = self._rng.randrange(2**32)
        effect_class = self._next_effect_class()
        self._last_played = effect_class
        self._inner = effect_class(seed=inner_seed, idle_secs=0)
        # Forward current terminal state
        if self._last_pty_update is not None:
            self._inner.on_pty_update(self._last_pty_update)
        self._shake.reset()

    def _start_cackling(self) -> None:
        self._phase = UnifiedPhase.CACKLING
        self._inner = None
        self._cackle_start = self._tick_count
        self._cackle_end = self._tick_count + round(5 * FPS)

    # -- Mascot rendering -------------------------------------------------

    def _merge_mascot(self, inner_outputs: list[OutputMessage]) -> list[OutputMessage]:
        """Flatten mascot on top of the inner effect's output.

        At overlapping positions, the mascot's character and fg win (so the
        mascot is visible), but the effect's bg is preserved (so the effect's
        destruction of the terminal content remains visible behind the mascot
        wireframe).  This prevents flicker while keeping the effect's coverage.

        If the inner effect emits OutputCells, the mascot is merged into the
        last OutputCells message (tattoy replaces the layer per message type,
        so a separate OutputCells would overwrite the effect). If the inner
        effect uses OutputPixels (e.g. microbes), the mascot goes as a
        separate OutputCells since they're distinct message types.
        """
        mascot_msgs = self._render_mascot()
        if not mascot_msgs:
            return inner_outputs

        mascot_msg = mascot_msgs[0]
        assert isinstance(mascot_msg, OutputCells)
        mascot_cells = mascot_msg.cells

        # Find the last OutputCells in inner_outputs to merge into
        for i in range(len(inner_outputs) - 1, -1, -1):
            msg = inner_outputs[i]
            if isinstance(msg, OutputCells):
                # Build lookup: position -> effect cell
                effect_by_pos = {tuple(c.coordinates): c for c in msg.cells}
                mascot_by_pos = {tuple(c.coordinates): c for c in mascot_cells}

                # Non-overlapping effect cells pass through unchanged
                merged = [c for c in msg.cells
                          if tuple(c.coordinates) not in mascot_by_pos]

                # Overlapping positions: mascot char/fg, effect bg
                for mc in mascot_cells:
                    pos = tuple(mc.coordinates)
                    ec = effect_by_pos.get(pos)
                    if ec is not None and ec.bg is not None:
                        merged.append(Cell(
                            character=mc.character,
                            coordinates=mc.coordinates,
                            fg=mc.fg,
                            bg=ec.bg,
                        ))
                    else:
                        merged.append(mc)

                inner_outputs[i] = OutputCells(cells=merged)
                return inner_outputs

        # No OutputCells in inner output (e.g. microbes uses OutputPixels) —
        # emit mascot as a separate message (different wire type, no conflict)
        return inner_outputs + mascot_msgs

    _PHASE_TO_STATE = {
        UnifiedPhase.WATCHING: "watching",
        UnifiedPhase.IMMINENT_EARLY: "imminent_early",
        UnifiedPhase.IMMINENT_DEEP: "imminent_deep",
        UnifiedPhase.ACTIVE: "active",
        UnifiedPhase.CACKLING: "cackling",
    }

    def _render_mascot(self) -> list[OutputMessage]:
        state = self._PHASE_TO_STATE.get(self._phase)
        if state is None:
            return []
        cells = render_mascot(state, self._tick_count, self._width, self._height)
        return [OutputCells(cells=cells)] if cells else []

    # -- Main tick --------------------------------------------------------

    def tick(self) -> list[OutputMessage]:
        self._tick_count += 1
        if not self._received_first_update:
            return []

        self._update_phase()

        if self._phase == UnifiedPhase.DONE:
            return []

        if self._phase == UnifiedPhase.ACTIVE:
            assert self._inner is not None
            inner_outputs = self._inner.tick()
            if self._inner.is_done:
                if self._demo_mode:
                    self._phase = UnifiedPhase.DONE
                    return []
                self._start_cackling()
            return self._merge_mascot(inner_outputs)

        if self._phase == UnifiedPhase.CACKLING:
            if self._tick_count >= self._cackle_end:
                if self._demo_mode:
                    self._phase = UnifiedPhase.DONE
                    return []
                else:
                    # Loop back to WATCHING
                    self._tick_count = BLINK_DURATION
                    self._phase = UnifiedPhase.WATCHING
                    self._compute_timing()
                    self._shake.reset()
            return self._render_mascot()

        # WATCHING, IMMINENT_EARLY, IMMINENT_DEEP — mascot only
        return self._render_mascot()
