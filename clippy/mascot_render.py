"""Shared mascot rendering — constants and cell generation.

Used by both MascotEffect (standalone --demo mascot) and UnifiedEffect
(mascot overlay during inner effect lifecycle).
"""
from __future__ import annotations

import math

from clippy.types import Cell, Color

FACE_W = 4       # max width in cells (cols 0-3)
FACE_H = 5       # height in rows (rows 0-4)
MARGIN = 1       # cells from right/bottom edge

BLINK_PERIOD = 100
BLINK_DURATION = 3

EYE_PULSE_PERIOD = 30
EYE_ALPHA_MIN = 0.7
EYE_ALPHA_MAX = 1.0

CACKLE_FLIP_TICKS = 10

# ---------------------------------------------------------------------------
# Face frame data
#
# Face layout (4 cols x 5 rows, relative coords):
#
#   row 0:  ╭──╮  outer loop top
#   row 1:  E╭╮E  eyes (E) flanking inner loop top
#   row 2:  ││╰╯  inner loop bottom + outer right side
#   row 3:  │╰─╯  inner curl close
#   row 4:  ╰──╯  outer curl close
#
# Each entry: (rel_col, rel_row, char, is_eye)
# is_eye=True -> rendered in eye color; False -> body color
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


def render_mascot(
    visual_state: str,
    tick_count: int,
    width: int,
    height: int,
) -> list[Cell]:
    """Render mascot cells for the given visual state.

    visual_state: "watching", "imminent_early", "imminent_deep", "active", "cackling"
    Returns an empty list if the terminal is too small.
    """
    corner_x = width - FACE_W - MARGIN
    corner_y = height - FACE_H - MARGIN
    if corner_x < 0 or corner_y < 0:
        return []

    t = tick_count

    # Colors
    if visual_state == "watching":
        body_color: Color = (0.6, 0.6, 0.6, 1.0)
        eye_color: Color = (1.0, 1.0, 1.0, 1.0)
    elif visual_state == "imminent_early":
        body_color = (1.0, 0.7, 0.0, 1.0)
        eye_color = (1.0, 0.7, 0.0, 1.0)
    elif visual_state in ("imminent_deep", "active"):
        alpha = EYE_ALPHA_MIN + (EYE_ALPHA_MAX - EYE_ALPHA_MIN) * (
            math.sin(2 * math.pi * t / EYE_PULSE_PERIOD) * 0.5 + 0.5
        )
        body_color = (1.0, 0.0, 0.0, alpha)
        eye_color = (1.0, 0.0, 0.0, alpha)
    else:  # cackling
        body_color = (1.0, 0.8, 0.0, 1.0)
        eye_color = (1.0, 1.0, 1.0, 1.0)

    # Build char list
    if visual_state in ("watching", "imminent_early", "imminent_deep", "active"):
        body_chars = _BODY_ROUNDED
        blink = visual_state == "watching" and t % BLINK_PERIOD < BLINK_DURATION
        if visual_state == "watching":
            eye_l = "─" if blink else "ʘ"
            eye_r = "─" if blink else "ʘ"
        elif visual_state == "imminent_early":
            eye_l = "◎"
            eye_r = "◎"
        else:  # imminent_deep or active
            eye_l = "◉"
            eye_r = "◉"
        all_chars = body_chars + [
            (_EYE_L_POS[0], _EYE_L_POS[1], eye_l, True),
            (_EYE_R_POS[0], _EYE_R_POS[1], eye_r, True),
        ]
    else:  # cackling
        frame = (t // CACKLE_FLIP_TICKS) % 2
        body_chars = _CACKLE_BODY_F0 if frame == 0 else _CACKLE_BODY_F1
        all_chars = body_chars + [
            (0, 1, ">", True),
            (1, 1, "▁", True),
            (2, 1, "▁", True),
            (3, 1, "<", True),
        ]

    return [
        Cell(
            character=char,
            coordinates=(corner_x + rc, corner_y + rr),
            fg=eye_color if is_eye else body_color,
            bg=None,
        )
        for rc, rr, char, is_eye in all_chars
    ]
