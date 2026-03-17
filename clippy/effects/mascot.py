#!/usr/bin/env python3
"""Clippy mascot overlay — watches from the corner with gleeful menace."""
from __future__ import annotations

import math
import os
from enum import IntEnum

from clippy.harness import run
from clippy.types import Cell, Color, CursorShakeDetector, OutputCells, OutputMessage, PTYUpdate, TTYResize

FPS = 30
FACE_W = 4       # max width in cells (cols 0–3)
FACE_H = 5       # height in rows (rows 0–4)
MARGIN = 1       # cells from right/bottom edge

BLINK_PERIOD = 100
BLINK_DURATION = 3

EYE_PULSE_PERIOD = 30
EYE_ALPHA_MIN = 0.7
EYE_ALPHA_MAX = 1.0

CACKLE_FLIP_TICKS = 10

DEMO_WATCHING_TICKS       = 30    # 1s watching
DEMO_IMMINENT_EARLY_TICKS = 150   # 5s raised eyebrows
DEMO_IMMINENT_DEEP_TICKS  = 150   # 5s angry red eyes
DEMO_CACKLING_TICKS       = 150   # 5s cackling


class Phase(IntEnum):
    WATCHING       = 0
    IMMINENT_EARLY = 1
    IMMINENT_DEEP  = 2
    CACKLING       = 3
    DONE           = 4


# ---------------------------------------------------------------------------
# Face frame data
#
# Face layout (4 cols × 5 rows, relative coords):
#
#   row 0:  ╭──╮  outer loop top
#   row 1:  E╭╮E  eyes (E) flanking inner loop top
#   row 2:  ││╰╯  inner loop bottom + outer right side
#   row 3:  │╰─╯  inner curl close
#   row 4:  ╰──╯  outer curl close
#
# Each entry: (rel_col, rel_row, char, is_eye)
# is_eye=True → rendered in eye color; False → body color
# ---------------------------------------------------------------------------

# Body chars for WATCHING / IMMINENT phases (rounded box drawing)
_BODY_ROUNDED: list[tuple[int, int, str, bool]] = [
    (0, 0, "╭", False), (1, 0, "─", False), (2, 0, "─", False), (3, 0, "╮", False),
    (1, 1, "╭", False), (2, 1, "╮", False),
    (0, 2, "│", False), (1, 2, "│", False), (2, 2, "╰", False), (3, 2, "╯", False),
    (0, 3, "│", False), (1, 3, "╰", False), (2, 3, "─", False), (3, 3, "╯", False),
    (0, 4, "╰", False), (1, 4, "─", False), (2, 4, "─", False), (3, 4, "╯", False),
]

# CACKLING body frame 0 — rounded corners, open mouth
_CACKLE_BODY_F0: list[tuple[int, int, str, bool]] = [
    (0, 0, "╭", False), (1, 0, "─", False), (2, 0, "─", False), (3, 0, "╮", False),
    (0, 2, "│", False), (1, 2, "╲", True),  (2, 2, "╱", True),  (3, 2, "╯", False),
    (0, 3, "│", False), (1, 3, "╰", False), (2, 3, "─", False), (3, 3, "╯", False),
    (0, 4, "╰", False), (1, 4, "─", False), (2, 4, "─", False), (3, 4, "╯", False),
]

# CACKLING body frame 1 — double-line corners, open mouth
_CACKLE_BODY_F1: list[tuple[int, int, str, bool]] = [
    (0, 0, "╔", False), (1, 0, "═", False), (2, 0, "═", False), (3, 0, "╗", False),
    (0, 2, "║", False), (1, 2, "╲", True),  (2, 2, "╱", True),  (3, 2, "╝", False),
    (0, 3, "║", False), (1, 3, "╚", False), (2, 3, "═", False), (3, 3, "╝", False),
    (0, 4, "╚", False), (1, 4, "═", False), (2, 4, "═", False), (3, 4, "╝", False),
]

# Eye char positions (col, row) for WATCHING/IMMINENT phases
_EYE_L_POS = (0, 1)
_EYE_R_POS = (3, 1)


# ---------------------------------------------------------------------------
# MascotEffect
# ---------------------------------------------------------------------------

class MascotEffect:
    EFFECT_META = {
        "name": "mascot",
        "description": "Clippy watches from the corner with gleeful menace",
        "overlay": True,
    }

    def __init__(self, seed: int | None = None, idle_secs: float | None = None) -> None:
        if idle_secs is None:
            idle_secs = float(os.environ.get("CLIPPY_INTERVAL", "300"))
        self._idle_secs = idle_secs
        self._demo_mode = idle_secs == 0
        self._tick_count = BLINK_DURATION
        self._phase = Phase.WATCHING
        self._width = 0
        self._height = 0
        self._received_first_update = False
        self._imminent_early_start = 0
        self._imminent_deep_start = 0
        self._cackle_start = 0
        self._cackle_end = 0

        # Cursor-shake skip
        self._shake = CursorShakeDetector()
        self._skip_requested = False

    # -- Timing -----------------------------------------------------------

    def _compute_timing(self) -> None:
        if self._demo_mode:
            self._imminent_early_start = DEMO_WATCHING_TICKS
            self._imminent_deep_start  = DEMO_WATCHING_TICKS + DEMO_IMMINENT_EARLY_TICKS
            self._cackle_start         = self._imminent_deep_start + DEMO_IMMINENT_DEEP_TICKS
            self._cackle_end           = self._cackle_start + DEMO_CACKLING_TICKS
        else:
            self._imminent_early_start = round((self._idle_secs - 15) * FPS)
            self._imminent_deep_start  = round((self._idle_secs - 10) * FPS)
            self._cackle_start         = round((self._idle_secs - 5)  * FPS)
            self._cackle_end           = round(self._idle_secs         * FPS)

    # -- Protocol callbacks -----------------------------------------------

    def on_pty_update(self, update: PTYUpdate) -> None:
        self._width, self._height = update.size
        if self._shake.update(update.cursor):
            self._skip_requested = True
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()

    def on_resize(self, resize: TTYResize) -> None:
        self._width, self._height = resize.width, resize.height
        if not self._received_first_update:
            self._received_first_update = True
            self._compute_timing()

    # -- Phase ------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def _update_phase(self) -> None:
        t = self._tick_count
        if self._phase == Phase.WATCHING and t >= self._imminent_early_start:
            self._phase = Phase.IMMINENT_EARLY
        elif self._phase == Phase.IMMINENT_EARLY and t >= self._imminent_deep_start:
            self._phase = Phase.IMMINENT_DEEP
        elif self._phase == Phase.IMMINENT_DEEP and t >= self._cackle_start:
            self._phase = Phase.CACKLING
        elif self._phase == Phase.CACKLING and t >= self._cackle_end:
            if self._demo_mode:
                self._phase = Phase.DONE
            else:
                self._tick_count = BLINK_DURATION
                self._phase = Phase.WATCHING
                self._compute_timing()

    # -- Rendering --------------------------------------------------------

    def _render(self) -> list[OutputMessage]:
        corner_x = self._width - FACE_W - MARGIN
        corner_y = self._height - FACE_H - MARGIN
        if corner_x < 0 or corner_y < 0:
            return []

        phase = self._phase
        t = self._tick_count

        # Colors
        if phase == Phase.WATCHING:
            body_color: Color = (0.6, 0.6, 0.6, 1.0)
            eye_color: Color  = (1.0, 1.0, 1.0, 1.0)
        elif phase == Phase.IMMINENT_EARLY:
            body_color = (1.0, 0.7, 0.0, 1.0)
            eye_color  = (1.0, 0.7, 0.0, 1.0)
        elif phase == Phase.IMMINENT_DEEP:
            alpha = EYE_ALPHA_MIN + (EYE_ALPHA_MAX - EYE_ALPHA_MIN) * (
                math.sin(2 * math.pi * t / EYE_PULSE_PERIOD) * 0.5 + 0.5
            )
            body_color = (1.0, 0.0, 0.0, alpha)
            eye_color  = (1.0, 0.0, 0.0, alpha)
        else:  # CACKLING
            body_color = (1.0, 0.8, 0.0, 1.0)
            eye_color  = (1.0, 1.0, 1.0, 1.0)

        # Build char list
        if phase in (Phase.WATCHING, Phase.IMMINENT_EARLY, Phase.IMMINENT_DEEP):
            body_chars = _BODY_ROUNDED
            blink = phase == Phase.WATCHING and t % BLINK_PERIOD < BLINK_DURATION
            if phase == Phase.WATCHING:
                eye_l = "─" if blink else "ʘ"
                eye_r = "─" if blink else "ʘ"
            elif phase == Phase.IMMINENT_EARLY:
                eye_l = "◎"
                eye_r = "◎"
            else:  # IMMINENT_DEEP
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
                (0, 1, ">",  True),
                (1, 1, "▁", True),
                (2, 1, "▁", True),
                (3, 1, "<",  True),
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
        # Cursor-shake: jump to IMMINENT_DEEP if still in early phases
        if self._skip_requested:
            if self._phase in (Phase.WATCHING, Phase.IMMINENT_EARLY):
                t = self._tick_count
                self._phase = Phase.IMMINENT_DEEP
                self._cackle_start = t + round(5 * FPS)
                self._cackle_end   = t + round(10 * FPS)
            self._skip_requested = False
        self._update_phase()
        if self._phase == Phase.DONE:
            return []
        return self._render()


if __name__ == "__main__":
    run(MascotEffect())
