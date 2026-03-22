"""Fake VS-Claudde IDE template for --demo mode.

build_template(width, height) → list[str]

Returns exactly `height` strings, each exactly `width` characters wide,
depicting a VS-Code-style Python editor showing Clippy's Revenge source.
Effects render on top of this background, visually destroying the code.
"""
from __future__ import annotations


def _p(s: str, w: int) -> str:
    """Pad s to exactly w chars (spaces), or truncate if longer."""
    return (s + " " * w)[:w]


# ---------------------------------------------------------------------------
# File explorer tree — 25 chars each, top-to-bottom
# ---------------------------------------------------------------------------

_TREE: list[str] = [
    " EXPLORER            ...",
    " v CLIPPYS-REVENGE",
    "   v clippy",
    "     v effects",
    "         fire.py",
    "         grove.py",
    "         invaders.py",
    "         mascot.py",
    "         microbes.py",
    "         paperclips.py",
    "       demo.py",
    "       harness.py",
    "       ide_template.py",
    "       launcher.py",
    "       mascot_render.py",
    "       noise.py",
    "       types.py",
    "       unified.py",
    "       unified_runner.py",
    "   v tests",
    "       test_fire.py",
    "       test_grove.py",
    "       test_harness.py",
    "       test_invaders.py",
    "       test_mascot.py",
    "       test_types.py",
    "       test_unified.py",
    "   > bin",
    "       clippy",
    "   CLAUDE.md",
    "   install.sh",
    "   uninstall.sh",
]

# ---------------------------------------------------------------------------
# Main editor — invaders.py source, up to 120 chars per line
# ---------------------------------------------------------------------------

_MAIN: list[str] = [
    "#!/usr/bin/env python3",
    '"""Space Invaders effect -- alien formation marches across the top third of the terminal.',
    "",
    "Aliens drop bombs that blast rubble into the user's code. When ~65% of the code",
    "zone is rubbled the effect fades out and exits.",
    '"""',
    "from __future__ import annotations",
    "",
    "import random",
    "from dataclasses import dataclass",
    "from enum import IntEnum",
    "",
    "from clippy.harness import run",
    "from clippy.types import Cell, Color, OutputCells, OutputMessage, PTYUpdate, TTYResize",
    "",
    "MARCH_TICKS        = 8     # ticks between formation moves  (~267ms @30fps)",
    "BOMB_FALL_TICKS    = 2     # ticks per bomb row drop",
    "ANIM_FLIP_TICKS    = 15    # ticks between sprite frame flips (~500ms @30fps)",
    "EXPLOSION_DURATION = 4     # ticks an explosion '*' lingers",
    "BLAST_RADIUS       = 2     # Manhattan-distance rubble scatter on impact",
    "FADE_DURATION      = 40    # ticks for FADING alpha fade-out",
    "BOMB_SPAWN_PROB    = 0.04  # probability per column per march step",
    "",
    "RUBBLE_THRESHOLD   = 0.65  # fraction of code zone cells rubbled -> FADING",
    "",
    "TOP_MARGIN          = 1    # blank rows above alien sprites",
    "ALIEN_SPRITE_HEIGHT = 3    # cell rows per sprite (6 pixel rows via half-blocks)",
    "ALIEN_ZONE_GAP      = 1    # blank rows below sprites, above code zone",
    "ALIEN_SPRITE_WIDTH  = 5    # characters per sprite row",
    "ALIEN_COL_STRIDE    = 6    # sprite width + 1 gap  (5+1)",
    "ALIEN_GENOME_BITS   = 18   # bits 0-17 determine 5x6 symmetric sprite",
    "ANIM_MASK_BITS      = 4    # bits to flip for animation frame 1",
    "",
    "ALIEN_COLOR     : Color = (0.0, 1.0, 0.0, 1.0)   # bright green",
    "BOMB_COLOR      : Color = (1.0, 1.0, 0.0, 1.0)   # yellow",
    "EXPLOSION_COLOR : Color = (1.0, 0.5, 0.0, 1.0)   # orange",
    "RUBBLE_COLOR    : Color = (0.4, 0.4, 0.4, 1.0)   # gray",
    "BLANK_BG        : Color = (0.0, 0.0, 0.05, 1.0)  # near-black bg for top zone",
    "",
    'RUBBLE_CHARS = list("░▒▓#$%&*+~.,`")',
    "",
    "_HALF_BLOCKS: dict[tuple[int, int], str] = {",
    '    (0, 0): " ",  (1, 0): "▀",',
    '    (0, 1): "▄",  (1, 1): "█",',
    "}",
    "",
    "",
    "class Phase(IntEnum):",
    "    IDLE   = 0",
    "    ACTIVE = 1",
    "    FADING = 2",
    "    DONE   = 3",
    "",
    "",
    "@dataclass(slots=True)",
    "class _Bomb:",
    "    x: int",
    "    y: int",
    "",
    "",
    "@dataclass(slots=True)",
    "class _Explosion:",
    "    x: int",
    "    y: int",
    "    born_tick: int",
    "",
    "",
    "def _make_sprite(genome: int) -> list[str]:",
    "    K = 6  # stride = number of pixel rows",
    "    col_offsets = [0, K, 2 * K, K, 0]",
    "    pixels = [",
    "        [(genome >> (col_offsets[x] + y)) & 1 for x in range(5)]",
    "        for y in range(K)",
    "    ]",
    "    rows = []",
    "    for cell_y in range(3):",
    "        top_y, bot_y = cell_y * 2, cell_y * 2 + 1",
    '        row = "".join(',
    "            _HALF_BLOCKS[(pixels[top_y][x], pixels[bot_y][x])]",
    "            for x in range(5)",
    "        )",
    "        rows.append(row)",
    "    return rows",
    "",
    "",
    "class InvadersEffect:",
    "    EFFECT_META = {",
    '        "name": "invaders",',
    '        "description": "Alien invaders blast your code to rubble",',
    "    }",
    "",
    "    def __init__(self, seed: int | None = None) -> None:",
    "        self._rng = random.Random(seed)",
    "        self._phase = Phase.IDLE",
    "        self._tick_count = 0",
    "        self._width = 0",
    "        self._height = 0",
    "        self._top_zone_height = 0",
    "        self._code_zone_start = 0",
    "        self._code_zone_cells = 0",
    "        self._sprites: list[list[list[str]]] = []",
    "        self._num_cols = 0",
    "        self._formation_x = 0",
    "        self._formation_y = 0",
    "        self._march_dir = 1",
    "        self._march_timer = 0",
    "        self._anim_frame = 0",
    "        self._anim_timer = 0",
    "        self._bombs: list[_Bomb] = []",
    "        self._bomb_timer = 0",
    "        self._explosions: list[_Explosion] = []",
    "        self._rubble: dict[tuple[int, int], str] = {}",
    "        self._rubble_count = 0",
    "        self._fade_start_tick = 0",
]

# ---------------------------------------------------------------------------
# Secondary editor — harness.py source, up to 54 chars per line
# ---------------------------------------------------------------------------

_RIGHT: list[str] = [
    '"""Effect protocol and harness.',
    "",
    "Provides Effect protocol, step()",
    "for deterministic testing, and",
    "run() for the full protocol loop.",
    '"""',
    "from __future__ import annotations",
    "",
    "import logging",
    "import os, queue, signal",
    "import sys, threading, time",
    "from pathlib import Path",
    "from typing import Protocol",
    "",
    "from clippy.types import (",
    "    OutputMessage, PTYUpdate,",
    "    TTYResize, from_json,",
    ")",
    "",
    "",
    "class Effect(Protocol):",
    "    def on_pty_update(",
    "        self, update: PTYUpdate,",
    "    ) -> None: ...",
    "    def on_resize(",
    "        self, resize: TTYResize,",
    "    ) -> None: ...",
    "    def tick(",
    "    ) -> list[OutputMessage]: ...",
    "",
    "",
    "def step(",
    "    effect: Effect,",
    "    messages: list[str],",
    ") -> list[str]:",
    '    """Single-tick test seam."""',
    "    for raw in messages:",
    "        msg = from_json(raw)",
    "        if msg is None:",
    "            continue",
    "        if isinstance(msg, PTYUpdate):",
    "            effect.on_pty_update(msg)",
    "        elif isinstance(msg, TTYResize):",
    "            effect.on_resize(msg)",
    "    outputs = effect.tick()",
    "    return [out.to_json()",
    "            for out in outputs]",
    "",
    "",
    "def run(",
    "    effect: Effect,",
    "    *,",
    "    fps: int = 30,",
    "    clock=None,",
    "    writer=None,",
    "    flush=None,",
    "    reader=None,",
    ") -> None:",
    '    """Run the effect loop."""',
    "    if clock is None:",
    "        clock = time.monotonic",
    "    if writer is None:",
    "        writer = sys.stdout.write",
    "    if flush is None:",
    "        flush = sys.stdout.flush",
    "    if reader is None:",
    "        reader = sys.stdin",
    "    frame_budget = 1.0 / max(1, fps)",
    "    shutdown = threading.Event()",
    "    msg_queue: queue.Queue = queue.Queue()",
    "",
    "    listener = threading.Thread(",
    "        target=_stdin_listener,",
    "        args=(reader, msg_queue,",
    "              shutdown, logger),",
    "        daemon=True,",
    "    )",
    "    listener.start()",
]


# ---------------------------------------------------------------------------
# Template builder
# ---------------------------------------------------------------------------

def build_template(width: int = 210, height: int = 49) -> list[str]:
    """Build fake IDE background as exactly height strings of exactly width chars.

    Layout scales with terminal size:
      width >= 160 : 3 panels  (tree | main editor | secondary)
      width >= 90  : 2 panels  (tree | main editor)
      width <  90  : 1 panel   (main editor only, no line numbers)
    """
    lines: list[str] = []

    # ── Decide panel widths ─────────────────────────────────────────────────
    if width >= 160:
        l_w = 25          # file tree
        r_w = min(60, width // 4)
        m_w = width - l_w - 1 - 1 - r_w   # two │ separators
        three_panels = True
        two_panels = True
    elif width >= 90:
        l_w = min(22, width // 5)
        m_w = width - l_w - 1             # one │ separator
        r_w = 0
        three_panels = False
        two_panels = True
    else:
        l_w = 0
        m_w = width
        r_w = 0
        three_panels = False
        two_panels = False

    # Main editor gutter: " NNN " (5 chars) when we have room
    gutter_w = 5 if m_w >= 40 else 0
    code_w = m_w - gutter_w

    # Right editor gutter: "NNN " (4 chars)
    r_gutter_w = 4 if r_w >= 20 else 0
    r_code_w = r_w - r_gutter_w

    content_rows = max(0, height - 5)   # rows 2 … height-4 inclusive

    # ── Row 0: title bar ─────────────────────────────────────────────────────
    title = "  \u25cf \u25cf \u25cf   VS Claudde  \u2014  Clippy's Revenge"
    lines.append(_p(title, width))

    # ── Row 1: tab bar ───────────────────────────────────────────────────────
    if three_panels:
        left_area  = _p("", l_w)
        main_tabs  = _p("  invaders.py [x]   harness.py   types.py   fire.py", m_w)
        right_tab  = _p("  harness.py", r_w)
        lines.append(left_area + "\u2502" + main_tabs + "\u2502" + right_tab)
    elif two_panels:
        left_area = _p("", l_w)
        main_tabs = _p("  invaders.py [x]   harness.py   types.py   fire.py", m_w)
        lines.append(left_area + "\u2502" + main_tabs)
    else:
        lines.append(_p("  invaders.py [x]   harness.py   types.py   fire.py", width))

    # ── Rows 2 … height-4: content area ──────────────────────────────────────
    for i in range(content_rows):
        line_num = i + 1

        # Left panel (file tree)
        if two_panels:
            tree_text = _TREE[i] if i < len(_TREE) else ""
            left_s = _p(tree_text, l_w)

        # Main editor (gutter + code)
        code_text = _MAIN[i] if i < len(_MAIN) else ""
        if gutter_w:
            gutter = f" {line_num:3} "      # " NNN " = 5 chars
            mid_s = _p(gutter + code_text, m_w)
        else:
            mid_s = _p(code_text, m_w)

        # Right panel (gutter + code)
        if three_panels:
            r_text = _RIGHT[i] if i < len(_RIGHT) else ""
            if r_gutter_w:
                r_gutter = f"{line_num:3} "  # "NNN " = 4 chars
                right_s = _p(r_gutter + r_text, r_w)
            else:
                right_s = _p(r_text, r_w)

        # Assemble row
        if three_panels:
            row = left_s + "\u2502" + mid_s + "\u2502" + right_s
        elif two_panels:
            row = left_s + "\u2502" + mid_s
        else:
            row = mid_s

        lines.append(_p(row, width))

    # ── Row height-4: separator before terminal panel ─────────────────────────
    lines.append("\u2500" * width)

    # ── Row height-3: terminal panel tab bar ─────────────────────────────────
    term_tabs = "  TERMINAL  OUTPUT  PROBLEMS  DEBUG CONSOLE  "
    lines.append(_p(term_tabs, width))

    # ── Row height-2: shell prompt ────────────────────────────────────────────
    prompt = "  ~/kramtime/Clippys-Revenge (main) $ python3 -m clippy.launcher --demo invaders"
    lines.append(_p(prompt, width))

    # ── Row height-1: status bar ──────────────────────────────────────────────
    status_l = "  main   Python   invaders.py "
    status_r = " Ln 1, Col 1   UTF-8   LF   Python 3.10.12  "
    gap = max(0, width - len(status_l) - len(status_r))
    lines.append(_p(status_l + " " * gap + status_r, width))

    # ── Ensure exactly height rows, each exactly width chars ──────────────────
    while len(lines) < height:
        lines.append(" " * width)
    lines = [_p(row, width) for row in lines[:height]]

    return lines
