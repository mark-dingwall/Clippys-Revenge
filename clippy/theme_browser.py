"""Interactive theme browser TUI.

Provides a terminal-based theme browser with arrow-key navigation,
search filtering, color swatches, and theme selection.
"""
from __future__ import annotations

import os
import re
import sys

from clippy.demo import _highlight_python
from clippy.ide_template import _RIGHT
from clippy.themes import (
    Theme,
    apply_theme,
    get_active_theme_name,
    load_all_themes,
    theme_to_demo_theme,
)


# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

def _ansi_fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _ansi_bg(r: int, g: int, b: int) -> str:
    return f"\033[48;2;{r};{g};{b}m"


def _lighten(rgb: tuple[int, int, int], pct: float) -> tuple[int, int, int]:
    """Lighten an RGB color by *pct* (0.0–1.0) toward white."""
    r, g, b = rgb
    return (
        min(255, int(r + (255 - r) * pct)),
        min(255, int(g + (255 - g) * pct)),
        min(255, int(b + (255 - b) * pct)),
    )


# ---------------------------------------------------------------------------
# ANSI-aware string helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def _visible_len(s: str) -> int:
    """String length ignoring ANSI escape sequences."""
    return len(_ANSI_RE.sub('', s))


def _truncate_ansi(s: str, max_width: int) -> str:
    """Truncate to max_width visible chars, preserving ANSI escapes."""
    out: list[str] = []
    vis = 0
    pos = 0
    for m in _ANSI_RE.finditer(s):
        for ch in s[pos:m.start()]:
            if vis >= max_width:
                return ''.join(out)
            out.append(ch)
            vis += 1
        out.append(m.group())
        pos = m.end()
    for ch in s[pos:]:
        if vis >= max_width:
            break
        out.append(ch)
        vis += 1
    return ''.join(out)


def _pad_ansi(s: str, width: int, bg: str) -> str:
    """Pad an ANSI string to exact visible width with bg-colored spaces."""
    vis = _visible_len(s)
    if vis >= width:
        return _truncate_ansi(s, width)
    return s + bg + ' ' * (width - vis)


# ---------------------------------------------------------------------------
# Color swatch rendering
# ---------------------------------------------------------------------------

def _render_swatch(theme: Theme) -> str:
    """Render 16 colored blocks showing the ANSI 0-15 palette."""
    colors = [
        theme.black, theme.red, theme.green, theme.yellow,
        theme.blue, theme.purple, theme.cyan, theme.white,
        theme.bright_black, theme.bright_red, theme.bright_green,
        theme.bright_yellow, theme.bright_blue, theme.bright_purple,
        theme.bright_cyan, theme.bright_white,
    ]
    parts = []
    for r, g, b in colors:
        parts.append(f"\033[48;2;{r};{g};{b}m  \033[0m")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Fallback: simple numbered list
# ---------------------------------------------------------------------------

def _browse_simple(themes: list[Theme], active_name: str | None) -> None:
    """Fallback browser when raw terminal I/O is unavailable."""
    print("\nAvailable themes:\n")
    for i, theme in enumerate(themes, 1):
        marker = " (active)" if theme.name.lower() == (active_name or "").lower() else ""
        swatch = _render_swatch(theme)
        print(f"  {i:3d}. {theme.name:30s} {swatch}{marker}")
    print()
    try:
        raw = input("Enter theme number (or q to quit): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if raw.lower() == "q" or not raw:
        return
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(themes):
            chosen = themes[idx]
            apply_theme(chosen)
            print(f"\nApplied theme: {chosen.name}")
        else:
            print("Invalid number.")
    except ValueError:
        print("Invalid input.")


# ---------------------------------------------------------------------------
# TUI browser (raw terminal mode)
# ---------------------------------------------------------------------------

def _browse_tui(themes: list[Theme], active_name: str | None) -> None:
    """Full TUI browser with arrow keys, search, and swatches."""
    import tty
    import termios

    if not themes:
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    # State
    cursor = 0
    scroll_offset = 0
    search = ""
    search_mode = False
    filtered = list(themes)

    def _filter():
        nonlocal filtered, cursor, scroll_offset
        if search:
            filtered = [t for t in themes if search.lower() in t.name.lower()]
        else:
            filtered = list(themes)
        cursor = 0
        scroll_offset = 0

    def _get_size():
        try:
            cols, rows = os.get_terminal_size(fd)
            return cols, rows
        except OSError:
            return 80, 24

    def _draw(preview: Theme) -> None:
        cols, rows = _get_size()
        visible_rows = rows - 6  # header(3) + footer(2) + search(1)
        if visible_rows < 1:
            visible_rows = 1

        # Adjust scroll
        nonlocal scroll_offset
        if cursor < scroll_offset:
            scroll_offset = cursor
        if cursor >= scroll_offset + visible_rows:
            scroll_offset = cursor - visible_rows + 1

        # Derive screen colors from the preview theme
        bg = _ansi_bg(*preview.background)
        fg = _ansi_fg(*preview.foreground)
        dim_fg = _ansi_fg(*preview.bright_black)
        accent_fg = _ansi_fg(*preview.cyan)
        sel_bg_rgb = preview.selection_background or _lighten(preview.background, 0.20)
        sel_bg = _ansi_bg(*sel_bg_rgb)

        # In raw mode \n is just line-feed (no carriage return), so every
        # newline must be \r\n to return the cursor to column 0.
        NL = "\r\n"
        # End-of-line: fill remainder with theme bg, then newline
        EOL = f"{bg}\033[K{NL}"

        # Two-column layout when terminal is wide enough
        show_preview = cols >= 120
        if show_preview:
            list_w = 73
            preview_w = cols - list_w - 1  # 1 for separator
            code_inner_w = preview_w - 2   # 1 left pad + 1 right pad
            demo_theme = theme_to_demo_theme(preview)
            code_bg = demo_theme.ide_bg
            # Pre-highlight code lines
            code_lines: list[str] = []
            for src in _RIGHT:
                highlighted = _highlight_python(src, demo_theme)
                code_lines.append(highlighted)

        def _right_col(code_idx: int) -> str:
            """Build right column content for a given code line index."""
            if not show_preview:
                return ""
            sep = f"{bg}{dim_fg}\u2502"
            if code_idx < len(code_lines):
                inner = _truncate_ansi(code_lines[code_idx], code_inner_w)
                padded = _pad_ansi(f" {inner} ", preview_w, code_bg)
            else:
                padded = code_bg + " " * preview_w
            return f"{sep}{padded}\033[0m"

        def _left_pad(content: str) -> str:
            """Pad left column to list_w when preview is shown."""
            if not show_preview:
                return content
            return _pad_ansi(content, list_w, bg)

        out = []
        out.append(f"\033[2J\033[H{bg}")  # clear + home + set bg
        code_idx = 0

        # Header row 0: separator
        left = f"{accent_fg}\033[1m{'─' * min(list_w if show_preview else cols, 60)}\033[0m"
        if show_preview:
            title_right = _pad_ansi(
                f"{code_bg}{fg}\033[1m Preview\033[0m", preview_w, code_bg
            )
            out.append(f"{_left_pad(left)}{bg}{dim_fg}\u2502{title_right}\033[0m{EOL}")
        else:
            out.append(f"{left}{EOL}")

        # Header row 1: title
        left = f"{bg}{fg}\033[1m Clippy Theme Browser\033[0m{bg}{dim_fg}  ({len(filtered)} themes)"
        code_right = _right_col(code_idx)
        code_idx += 1
        out.append(f"{_left_pad(left)}{code_right}{EOL}")

        # Header row 2: separator
        left = f"{accent_fg}\033[1m{'─' * min(list_w if show_preview else cols, 60)}\033[0m"
        if show_preview:
            sep_right = _pad_ansi(
                f"{code_bg}{demo_theme.sep_fg}{'─' * (preview_w - 2)}", preview_w, code_bg
            )
            out.append(f"{_left_pad(left)}{bg}{dim_fg}\u2502{sep_right}\033[0m{EOL}")
            code_idx += 1
        else:
            out.append(f"{left}{EOL}")

        # Search bar
        if search_mode:
            left = f"{bg}{fg} / Search: {search}"
        elif search:
            left = f"{bg}{fg} / Search: {search}{dim_fg} (press / to edit)"
        else:
            left = f"{bg}{dim_fg} / to search"
        code_right = _right_col(code_idx)
        code_idx += 1
        out.append(f"{_left_pad(left)}{code_right}{EOL}")

        # Theme list
        for i in range(scroll_offset, min(scroll_offset + visible_rows, len(filtered))):
            theme = filtered[i]
            is_active = theme.name.lower() == (active_name or "").lower()
            is_cursor = (i == cursor)
            swatch = _render_swatch(theme)
            marker = f"{dim_fg} (active)" if is_active else ""

            if is_cursor:
                left = f"{sel_bg}{fg}\033[1m > {theme.name:28s}\033[0m {swatch}{marker}"
            else:
                left = f"{bg}{fg}   {theme.name:28s} {swatch}{marker}"
            code_right = _right_col(code_idx)
            code_idx += 1
            out.append(f"{_left_pad(left)}{code_right}{EOL}")

        # Pad remaining rows
        for _ in range(visible_rows - min(visible_rows, len(filtered) - scroll_offset)):
            code_right = _right_col(code_idx)
            code_idx += 1
            out.append(f"{_left_pad('')}{code_right}{EOL}")

        # Footer
        left = f"{accent_fg}\033[1m{'─' * min(list_w if show_preview else cols, 60)}\033[0m"
        code_right = _right_col(code_idx)
        code_idx += 1
        out.append(f"{_left_pad(left)}{code_right}{EOL}")

        left = f"{bg}{dim_fg} ↑↓ navigate  / search  Enter select  q quit\033[0m"
        code_right = _right_col(code_idx)
        out.append(f"{_left_pad(left)}{code_right}{bg}\033[K")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _read_key():
        ch = sys.stdin.read(1)
        if not ch:
            raise EOFError
        if ch == "\033":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                elif ch3 == "B":
                    return "DOWN"
                elif ch3 == "C":
                    return "RIGHT"
                elif ch3 == "D":
                    return "LEFT"
                return "ESC"
            return "ESC"
        return ch

    # Enter alt screen + raw mode
    sys.stdout.write("\033[?1049h")  # alt screen on
    sys.stdout.write("\033[?25l")    # hide cursor
    sys.stdout.flush()

    try:
        tty.setraw(fd)
        _draw(filtered[cursor] if filtered else themes[0])

        while True:
            key = _read_key()

            if search_mode:
                if key in ("\r", "\n"):
                    search_mode = False
                elif key == "\x7f" or key == "\x08":  # backspace
                    search = search[:-1]
                    _filter()
                elif key == "ESC":
                    search = ""
                    search_mode = False
                    _filter()
                elif key.isprintable() and len(key) == 1:
                    search += key
                    _filter()
            else:
                if key == "q" or key == "ESC":
                    break
                elif key == "/":
                    search_mode = True
                elif key == "UP" or key == "k":
                    if cursor > 0:
                        cursor -= 1
                elif key == "DOWN" or key == "j":
                    if cursor < len(filtered) - 1:
                        cursor += 1
                elif key in ("\r", "\n"):
                    if filtered:
                        chosen = filtered[cursor]
                        apply_theme(chosen)
                        # Brief flash to confirm
                        cbg = _ansi_bg(*chosen.background)
                        cfg = _ansi_fg(*chosen.foreground)
                        sys.stdout.write(f"\033[2J\033[H{cbg}{cfg}\r\n Applied: {chosen.name}\033[0m\r\n")
                        sys.stdout.flush()
                        import time
                        time.sleep(0.5)
                    break

            _draw(filtered[cursor] if filtered else themes[0])

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h")    # show cursor
        sys.stdout.write("\033[?1049l")  # alt screen off
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def browse_themes() -> None:
    """Launch the theme browser (TUI if possible, fallback to simple list)."""
    themes = load_all_themes()
    if not themes:
        print("No themes available.", file=sys.stderr)
        return

    active_name = get_active_theme_name()

    # Try TUI mode; fall back to simple list if terminal not available
    try:
        import tty    # noqa: F401
        import termios  # noqa: F401
        if not sys.stdin.isatty():
            raise ImportError("stdin not a tty")
        _browse_tui(themes, active_name)
    except (ImportError, AttributeError, OSError):
        _browse_simple(themes, active_name)
