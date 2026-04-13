"""Demo mode — ANSI renderer and terminal preview loop.

Renders effect output directly to the terminal using ANSI escape codes,
allowing users to preview effects without tattoy installed.
"""
from __future__ import annotations

import re
import sys
import threading
import time

from clippy.ide_template import build_template
from clippy.themes import DemoTheme, default_demo_theme
from clippy.types import Cell, Color, OutputCells, OutputMessage, OutputPixels, OutputText

# ---------------------------------------------------------------------------
# ANSI constants
# ---------------------------------------------------------------------------

RESET = "\033[0m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
CLEAR = "\033[2J"


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

def _clamp(v: float) -> int:
    """Clamp a 0.0–1.0 float to 0–255 int."""
    return max(0, min(255, int(v * 255)))


def color_to_fg(c: Color | None) -> str:
    """Convert RGBA float color to ANSI 24-bit foreground escape. Empty string if None."""
    if c is None:
        return ""
    r, g, b, a = c
    return f"\033[38;2;{_clamp(r * a)};{_clamp(g * a)};{_clamp(b * a)}m"


def color_to_bg(c: Color | None) -> str:
    """Convert RGBA float color to ANSI 24-bit background escape. Empty string if None."""
    if c is None:
        return ""
    r, g, b, a = c
    return f"\033[48;2;{_clamp(r * a)};{_clamp(g * a)};{_clamp(b * a)}m"


def move_to(x: int, y: int) -> str:
    """ANSI cursor positioning (0-indexed input, 1-indexed output)."""
    return f"\033[{y + 1};{x + 1}H"


# ---------------------------------------------------------------------------
# Frame renderer
# ---------------------------------------------------------------------------

def render_frame(outputs: list[OutputMessage], writer, flush) -> None:
    """Render a list of OutputMessages as ANSI escape sequences."""
    for out in outputs:
        if isinstance(out, OutputCells):
            for cell in out.cells:
                x, y = cell.coordinates
                seq = move_to(x, y) + color_to_fg(cell.fg) + color_to_bg(cell.bg) + cell.character + RESET
                writer(seq)

        elif isinstance(out, OutputText):
            x, y = out.coordinates
            seq = move_to(x, y) + color_to_fg(out.fg) + color_to_bg(out.bg) + out.text + RESET
            writer(seq)

        elif isinstance(out, OutputPixels):
            for pixel in out.pixels:
                if pixel.color is None:
                    continue  # ghost erasure — not renderable in demo mode
                x, py = pixel.coordinates
                cell_y = py // 2
                ch = "\u2580" if py % 2 == 0 else "\u2584"  # ▀ upper, ▄ lower
                seq = move_to(x, cell_y) + color_to_fg(pixel.color) + ch + RESET
                writer(seq)

    flush()


# ---------------------------------------------------------------------------
# IDE template renderer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Python syntax highlighting
# ---------------------------------------------------------------------------

_KEYWORDS = frozenset([
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
    "try", "while", "with", "yield",
])

_TOKEN_RE = re.compile(
    r'(\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\')'  # triple-quoted strings
    r'|(\"[^\"\\]*(?:\\.[^\"\\]*)*\"|\'[^\'\\]*(?:\\.[^\'\\]*)*\')'  # strings
    r'|(#.*)'                                         # comments
    r'|(\b\d+\.?\d*\b)'                              # numbers
    r'|([A-Za-z_]\w*)'                               # identifiers / keywords
    r'|([ \t]+|[^\w\s]+)'                            # whitespace / punctuation
)


def _highlight_python(s: str, theme: DemoTheme) -> str:
    """Apply syntax colors to a Python source line using the given theme."""
    result = [theme.code_fg]
    prev_kw = ""
    for m in _TOKEN_RE.finditer(s):
        triple, string, comment, number, ident, other = m.groups()
        tok = m.group()
        if triple is not None or string is not None:
            result.append(theme.str_fg + tok + theme.code_fg)
            prev_kw = ""
        elif comment is not None:
            result.append(theme.cmt_fg + tok)
            break  # rest of line is a comment
        elif number is not None:
            result.append(theme.num_fg + tok + theme.code_fg)
            prev_kw = ""
        elif ident is not None:
            if tok in _KEYWORDS:
                result.append(theme.kw_fg + tok + theme.code_fg)
                prev_kw = tok
            elif prev_kw in ("def", "class"):
                result.append(theme.func_fg + tok + theme.code_fg)
                prev_kw = ""
            else:
                result.append(tok)
                prev_kw = ""
        else:
            result.append(tok)
    return "".join(result)


def _render_toast(msg: str, width: int, is_native: bool, writer) -> None:
    """Render a full-width toast bar at the top of the screen."""
    padded = msg.center(width)[:width]
    if is_native:
        bg = "\033[48;2;20;60;20m"
        fg = "\033[38;2;120;220;120m"
    else:
        bg = "\033[48;2;60;50;15m"
        fg = "\033[38;2;220;190;80m"
    writer(move_to(0, 0) + bg + fg + padded + RESET)


def _render_ide_template(width: int, height: int, writer, theme: DemoTheme) -> None:
    """Write the fake IDE background to the terminal (no flush)."""
    rows = build_template(width, height)
    for y, row in enumerate(rows):
        if y == 0:
            writer(move_to(0, y) + theme.bar_bg + theme.ide_fg + row + RESET)
        elif y == 1:
            writer(move_to(0, y) + theme.bar_bg + theme.ide_fg + row + RESET)
        elif y == height - 1:
            writer(move_to(0, y) + theme.stat_bg + theme.stat_fg + row + RESET)
        elif y >= height - 4:
            writer(move_to(0, y) + theme.term_bg + theme.ide_fg + row + RESET)
        else:
            writer(move_to(0, y) + theme.ide_bg + _highlight_python(row, theme) + RESET)


# ---------------------------------------------------------------------------
# Demo loop
# ---------------------------------------------------------------------------

def demo_run(
    effect,
    width: int,
    height: int,
    *,
    fps: int = 30,
    clock=None,
    sleep=None,
    writer=None,
    flush=None,
    toast: str | None = None,
    toast_is_native: bool = False,
    theme: DemoTheme | None = None,
) -> None:
    """Run an effect in demo mode, rendering directly to terminal.

    All keyword args after height are testability seams.
    """
    if theme is None:
        theme = default_demo_theme()
    if clock is None:
        clock = time.monotonic
    if writer is None:
        writer = sys.stdout.write
    if flush is None:
        flush = sys.stdout.flush

    shutdown = threading.Event()

    if sleep is None:
        def sleep(timeout):
            shutdown.wait(timeout=timeout)

    frame_budget = 1.0 / fps

    from clippy.types import PTYUpdate
    rows = build_template(width, height)
    demo_cells = [
        Cell(character=ch, coordinates=(x, y), fg=None, bg=None)
        for y, row in enumerate(rows)
        for x, ch in enumerate(row)
        if ch != " "
    ]
    effect.on_pty_update(PTYUpdate(size=(width, height), cells=demo_cells, cursor=(0, 0)))

    toast_frames = int(2.0 * fps) if toast else 0
    frame_count = 0

    writer(ALT_SCREEN_ON)
    writer(HIDE_CURSOR)
    writer(CLEAR)
    _render_ide_template(width, height, writer, theme)
    if toast:
        _render_toast(toast, width, toast_is_native, writer)
    flush()

    try:
        while True:
            frame_start = clock()
            frame_count += 1

            outputs = effect.tick()
            if outputs:
                render_frame(outputs, writer, flush)

            if toast:
                if frame_count <= toast_frames:
                    _render_toast(toast, width, toast_is_native, writer)
                    flush()
                elif frame_count == toast_frames + 1:
                    # Restore title bar underneath
                    writer(move_to(0, 0) + theme.bar_bg + theme.ide_fg + rows[0] + RESET)
                    flush()

            # Stop if effect declares itself done
            if effect.is_done:
                break

            elapsed = clock() - frame_start
            remaining = frame_budget - elapsed
            if remaining > 0:
                sleep(remaining)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        writer(SHOW_CURSOR)
        writer(ALT_SCREEN_OFF)
        flush()
