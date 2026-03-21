"""Unified effect — single state machine wrapping an inner effect + mascot overlay."""
from __future__ import annotations

import math
import os
import random
from enum import IntEnum

from clippy.types import (
    Cell,
    Color,
    CursorShakeDetector,
    OutputCells,
    OutputMessage,
    PTYUpdate,
    TTYResize,
)

FPS = 30

# ---------------------------------------------------------------------------
# Mascot rendering constants (from mascot.py)
# ---------------------------------------------------------------------------

FACE_W = 4
FACE_H = 5
MARGIN = 1

BLINK_PERIOD = 100
BLINK_DURATION = 3

EYE_PULSE_PERIOD = 30
EYE_ALPHA_MIN = 0.7
EYE_ALPHA_MAX = 1.0

CACKLE_FLIP_TICKS = 10


# Body chars for WATCHING / IMMINENT phases (rounded box drawing)
_BODY_ROUNDED: list[tuple[int, int, str, bool]] = [
    (0, 0, "╭", False), (1, 0, "─", False), (2, 0, "─", False), (3, 0, "╮", False),
    (1, 1, "╭", False), (2, 1, "╮", False),
    (0, 2, "│", False), (1, 2, "│", False), (2, 2, "╰", False), (3, 2, "╯", False),
    (0, 3, "│", False), (1, 3, "╰", False), (2, 3, "─", False), (3, 3, "╯", False),
    (0, 4, "╰", False), (1, 4, "─", False), (2, 4, "─", False), (3, 4, "╯", False),
]

_CACKLE_BODY_F0: list[tuple[int, int, str, bool]] = [
    (0, 0, "╭", False), (1, 0, "─", False), (2, 0, "─", False), (3, 0, "╮", False),
    (0, 2, "│", False), (1, 2, "╲", True),  (2, 2, "╱", True),  (3, 2, "╯", False),
    (0, 3, "│", False), (1, 3, "╰", False), (2, 3, "─", False), (3, 3, "╯", False),
    (0, 4, "╰", False), (1, 4, "─", False), (2, 4, "─", False), (3, 4, "╯", False),
]

_CACKLE_BODY_F1: list[tuple[int, int, str, bool]] = [
    (0, 0, "╔", False), (1, 0, "═", False), (2, 0, "═", False), (3, 0, "╗", False),
    (0, 2, "║", False), (1, 2, "╲", True),  (2, 2, "╱", True),  (3, 2, "╝", False),
    (0, 3, "║", False), (1, 3, "╚", False), (2, 3, "═", False), (3, 3, "╝", False),
    (0, 4, "╚", False), (1, 4, "═", False), (2, 4, "═", False), (3, 4, "╝", False),
]

_EYE_L_POS = (0, 1)
_EYE_R_POS = (3, 1)


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
        self._inner = None  # type: ignore[assignment]
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
        """Merge mascot cells into the inner effect's output.

        If the inner effect emits OutputCells, append mascot cells to the last
        OutputCells message (tattoy replaces the layer per message type, so a
        separate OutputCells would overwrite the effect). If the inner effect
        uses OutputPixels (e.g. microbes), the mascot goes as a separate
        OutputCells since they're distinct message types.
        """
        mascot_msgs = self._render_mascot()
        if not mascot_msgs:
            return inner_outputs

        mascot_cells = mascot_msgs[0].cells  # always OutputCells

        # Find the last OutputCells in inner_outputs to merge into
        for i in range(len(inner_outputs) - 1, -1, -1):
            if isinstance(inner_outputs[i], OutputCells):
                inner_outputs[i] = OutputCells(
                    cells=inner_outputs[i].cells + mascot_cells,
                )
                return inner_outputs

        # No OutputCells in inner output (e.g. microbes uses OutputPixels) —
        # emit mascot as a separate message (different wire type, no conflict)
        return inner_outputs + mascot_msgs

    def _render_mascot(self) -> list[OutputMessage]:
        corner_x = self._width - FACE_W - MARGIN
        corner_y = self._height - FACE_H - MARGIN
        if corner_x < 0 or corner_y < 0:
            return []

        phase = self._phase
        t = self._tick_count

        # Map unified phase to mascot appearance
        if phase == UnifiedPhase.WATCHING:
            body_color: Color = (0.6, 0.6, 0.6, 1.0)
            eye_color: Color = (1.0, 1.0, 1.0, 1.0)
        elif phase == UnifiedPhase.IMMINENT_EARLY:
            body_color = (1.0, 0.7, 0.0, 1.0)
            eye_color = (1.0, 0.7, 0.0, 1.0)
        elif phase in (UnifiedPhase.IMMINENT_DEEP, UnifiedPhase.ACTIVE):
            # Red pulsing eyes — same appearance for both
            alpha = EYE_ALPHA_MIN + (EYE_ALPHA_MAX - EYE_ALPHA_MIN) * (
                math.sin(2 * math.pi * t / EYE_PULSE_PERIOD) * 0.5 + 0.5
            )
            body_color = (1.0, 0.0, 0.0, alpha)
            eye_color = (1.0, 0.0, 0.0, alpha)
        else:  # CACKLING
            body_color = (1.0, 0.8, 0.0, 1.0)
            eye_color = (1.0, 1.0, 1.0, 1.0)

        # Build char list
        if phase in (UnifiedPhase.WATCHING, UnifiedPhase.IMMINENT_EARLY,
                     UnifiedPhase.IMMINENT_DEEP, UnifiedPhase.ACTIVE):
            body_chars = _BODY_ROUNDED
            blink = phase == UnifiedPhase.WATCHING and t % BLINK_PERIOD < BLINK_DURATION
            if phase == UnifiedPhase.WATCHING:
                eye_l = "─" if blink else "ʘ"
                eye_r = "─" if blink else "ʘ"
            elif phase == UnifiedPhase.IMMINENT_EARLY:
                eye_l = "◎"
                eye_r = "◎"
            else:  # IMMINENT_DEEP or ACTIVE
                eye_l = "◉"
                eye_r = "◉"
            all_chars = body_chars + [
                (_EYE_L_POS[0], _EYE_L_POS[1], eye_l, True),
                (_EYE_R_POS[0], _EYE_R_POS[1], eye_r, True),
            ]
        else:  # CACKLING
            frame = (t // CACKLE_FLIP_TICKS) % 2
            body_chars = _CACKLE_BODY_F0 if frame == 0 else _CACKLE_BODY_F1
            all_chars = body_chars + [
                (0, 1, ">", True),
                (1, 1, "▁", True),
                (2, 1, "▁", True),
                (3, 1, "<", True),
            ]

        cells = [
            Cell(
                character=char,
                coordinates=(corner_x + rc, corner_y + rr),
                fg=eye_color if is_eye else body_color,
                bg=None,
            )
            for rc, rr, char, is_eye in all_chars
        ]
        return [OutputCells(cells=cells)]

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
