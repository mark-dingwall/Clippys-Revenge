"""Interactive theme browser TUI.

Provides a terminal-based theme browser with arrow-key navigation,
search filtering, color swatches, and theme selection.
"""
from __future__ import annotations

import sys

from clippy.themes import (
    DemoTheme,
    Theme,
    apply_theme,
    get_active_theme_name,
    load_all_themes,
    theme_to_demo_theme,
)


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
            import os
            cols, rows = os.get_terminal_size()
            return cols, rows
        except OSError:
            return 80, 24

    def _draw():
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

        # In raw mode \n is just line-feed (no carriage return), so every
        # newline must be \r\n to return the cursor to column 0.
        NL = "\r\n"

        out = []
        out.append("\033[2J\033[H")  # clear + home

        # Header
        out.append(f"\033[1m{'─' * min(cols, 60)}\033[0m{NL}")
        out.append(f"\033[1m Clippy Theme Browser\033[0m  ({len(filtered)} themes){NL}")
        out.append(f"\033[1m{'─' * min(cols, 60)}\033[0m{NL}")

        # Search bar
        if search_mode:
            out.append(f" / Search: {search}\033[K{NL}")
        elif search:
            out.append(f" / Search: {search} (press / to edit)\033[K{NL}")
        else:
            out.append(f" / to search\033[K{NL}")

        # Theme list
        for i in range(scroll_offset, min(scroll_offset + visible_rows, len(filtered))):
            theme = filtered[i]
            is_active = theme.name.lower() == (active_name or "").lower()
            is_cursor = (i == cursor)
            swatch = _render_swatch(theme)
            marker = " (active)" if is_active else ""

            if is_cursor:
                out.append(f"\033[7m > {theme.name:28s}\033[0m {swatch}{marker}\033[K{NL}")
            else:
                out.append(f"   {theme.name:28s} {swatch}{marker}\033[K{NL}")

        # Pad remaining rows
        for _ in range(visible_rows - min(visible_rows, len(filtered) - scroll_offset)):
            out.append(f"\033[K{NL}")

        # Footer
        out.append(f"\033[1m{'─' * min(cols, 60)}\033[0m{NL}")
        out.append(" \033[2m↑↓ navigate  / search  Enter select  q quit\033[0m\033[K")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _read_key():
        ch = sys.stdin.read(1)
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
        _draw()

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
                        sys.stdout.write(f"\033[2J\033[H\r\n Applied: {chosen.name}\r\n")
                        sys.stdout.flush()
                        import time
                        time.sleep(0.5)
                    break

            _draw()

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
