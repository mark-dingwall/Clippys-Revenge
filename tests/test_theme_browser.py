"""Tests for clippy.theme_browser — TUI theme browser with mocked terminal I/O."""
from __future__ import annotations

import io
from unittest import mock

import pytest

from clippy.theme_browser import (
    _render_swatch, _browse_simple, _browse_tui, browse_themes,
    _visible_len, _truncate_ansi, _pad_ansi,
)
from clippy.themes import Theme, default_theme


def _make_theme(name: str = "Test Theme") -> Theme:
    return Theme(
        name=name,
        background=(0, 0, 0),
        foreground=(255, 255, 255),
        black=(0, 0, 0), red=(255, 0, 0), green=(0, 255, 0),
        yellow=(255, 255, 0), blue=(0, 0, 255), purple=(128, 0, 128),
        cyan=(0, 255, 255), white=(192, 192, 192),
        bright_black=(128, 128, 128), bright_red=(255, 128, 128),
        bright_green=(128, 255, 128), bright_yellow=(255, 255, 128),
        bright_blue=(128, 128, 255), bright_purple=(255, 128, 255),
        bright_cyan=(128, 255, 255), bright_white=(255, 255, 255),
    )


# ---------------------------------------------------------------------------
# Swatch rendering
# ---------------------------------------------------------------------------

class TestRenderSwatch:
    def test_returns_ansi_sequences(self):
        swatch = _render_swatch(_make_theme())
        assert "\033[48;2;" in swatch
        assert "\033[0m" in swatch

    def test_contains_16_blocks(self):
        swatch = _render_swatch(_make_theme())
        # Each color block is "  " (2 spaces) between bg set and reset
        assert swatch.count("\033[0m") == 16

    def test_uses_theme_colors(self):
        theme = _make_theme()
        swatch = _render_swatch(theme)
        # Red color (255, 0, 0) should appear
        assert "255;0;0" in swatch


# ---------------------------------------------------------------------------
# Simple browser fallback
# ---------------------------------------------------------------------------

class TestBrowseSimple:
    def test_quit(self, capsys):
        """Entering 'q' exits without applying a theme."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        with mock.patch("builtins.input", return_value="q"):
            _browse_simple(themes, None)
        out = capsys.readouterr().out
        assert "Alpha" in out
        assert "Beta" in out

    def test_select_theme(self, capsys):
        """Entering a valid number applies the theme."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        with mock.patch("builtins.input", return_value="2"), \
             mock.patch("clippy.theme_browser.apply_theme") as mock_apply:
            _browse_simple(themes, None)
        mock_apply.assert_called_once()
        assert mock_apply.call_args[0][0].name == "Beta"

    def test_invalid_number(self, capsys):
        themes = [_make_theme("Alpha")]
        with mock.patch("builtins.input", return_value="99"):
            _browse_simple(themes, None)
        out = capsys.readouterr().out
        assert "Invalid number" in out

    def test_empty_input_exits(self, capsys):
        themes = [_make_theme("Alpha")]
        with mock.patch("builtins.input", return_value=""):
            _browse_simple(themes, None)

    def test_active_marker(self, capsys):
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        with mock.patch("builtins.input", return_value="q"):
            _browse_simple(themes, "Alpha")
        out = capsys.readouterr().out
        assert "(active)" in out

    def test_eof_exits_gracefully(self, capsys):
        themes = [_make_theme("Alpha")]
        with mock.patch("builtins.input", side_effect=EOFError):
            _browse_simple(themes, None)

    def test_keyboard_interrupt_exits(self, capsys):
        themes = [_make_theme("Alpha")]
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            _browse_simple(themes, None)


# ---------------------------------------------------------------------------
# TUI browser (mocked terminal)
# ---------------------------------------------------------------------------

class TestBrowseTui:
    """Test the full TUI browser with mocked raw terminal I/O."""

    def _run_tui(self, themes, keys, active_name=None, term_size=(80, 24)):
        """Run _browse_tui with mocked terminal, returning captured stdout.

        *keys* is a string of characters fed to stdin.read(1) in order.
        """
        buf = io.StringIO()
        key_iter = iter(keys)

        def fake_read(n):
            try:
                return next(key_iter)
            except StopIteration:
                raise KeyboardInterrupt  # end the loop

        mock_stdin = mock.MagicMock()
        mock_stdin.fileno.return_value = 0
        mock_stdin.read.side_effect = fake_read

        fake_settings = [0] * 7  # dummy termios settings
        with mock.patch("sys.stdin", mock_stdin), \
             mock.patch("sys.stdout", buf), \
             mock.patch("tty.setraw"), \
             mock.patch("termios.tcgetattr", return_value=fake_settings), \
             mock.patch("termios.tcsetattr"), \
             mock.patch("os.get_terminal_size", return_value=term_size):
            _browse_tui(themes, active_name)

        return buf.getvalue()

    def test_raw_mode_uses_cr_lf(self):
        """In raw mode, every line must use \\r\\n (not bare \\n)."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q")
        # Every \n must be preceded by \r
        lines_with_bare_lf = []
        for i, ch in enumerate(output):
            if ch == "\n" and (i == 0 or output[i - 1] != "\r"):
                # Find context around the bare \n
                start = max(0, i - 30)
                end = min(len(output), i + 10)
                lines_with_bare_lf.append(repr(output[start:end]))
        assert lines_with_bare_lf == [], (
            f"Found bare \\n (no \\r) in TUI output at: {lines_with_bare_lf[:3]}"
        )

    def test_header_visible(self):
        """TUI output contains the header title."""
        themes = [_make_theme("Alpha")]
        output = self._run_tui(themes, "q")
        assert "Clippy Theme Browser" in output

    def test_theme_names_visible(self):
        """Theme names appear in the TUI output."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q")
        assert "Alpha" in output
        assert "Beta" in output

    def test_footer_visible(self):
        """Navigation hints appear in the footer."""
        themes = [_make_theme("Alpha")]
        output = self._run_tui(themes, "q")
        assert "navigate" in output
        assert "search" in output
        assert "quit" in output

    def test_active_theme_marker(self):
        """Active theme shows '(active)' marker."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q", active_name="Alpha")
        assert "(active)" in output

    def test_cursor_navigation_down(self):
        """Arrow down moves cursor to next theme."""
        themes = [_make_theme("Alpha"), _make_theme("Beta"), _make_theme("Gamma")]
        # Press down twice, then quit
        output = self._run_tui(themes, "\033[B\033[Bq")
        # Should have re-drawn with cursor on Gamma (index 2)
        # The last draw should have Gamma highlighted (inverse video)
        assert "Gamma" in output

    def test_search_filters(self):
        """Typing /al filters to themes matching 'al'."""
        themes = [_make_theme("Alpha"), _make_theme("Beta"), _make_theme("Gamma")]
        # / enters search, type "al", press Enter to exit search, q to quit
        output = self._run_tui(themes, "/al\rq")
        # After filtering, only Alpha should be shown (last draw)
        # Beta and Gamma should still appear in earlier draws but the
        # filtered count should show "1 themes"
        assert "1 themes" in output

    def test_enter_selects_theme(self):
        """Pressing Enter applies the selected theme."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        with mock.patch("clippy.theme_browser.apply_theme") as mock_apply, \
             mock.patch("time.sleep"):
            output = self._run_tui(themes, "\r")
        mock_apply.assert_called_once()
        assert mock_apply.call_args[0][0].name == "Alpha"

    def test_escape_exits(self):
        """Pressing Escape quits without applying."""
        themes = [_make_theme("Alpha")]
        with mock.patch("clippy.theme_browser.apply_theme") as mock_apply:
            output = self._run_tui(themes, "\033")
        mock_apply.assert_not_called()

    def test_alt_screen_on_and_off(self):
        """TUI enables and restores alt screen buffer."""
        themes = [_make_theme("Alpha")]
        output = self._run_tui(themes, "q")
        assert "\033[?1049h" in output  # alt screen on
        assert "\033[?1049l" in output  # alt screen off

    def test_cursor_hidden_and_restored(self):
        """TUI hides cursor during browse and restores on exit."""
        themes = [_make_theme("Alpha")]
        output = self._run_tui(themes, "q")
        assert "\033[?25l" in output  # hide cursor
        assert "\033[?25h" in output  # show cursor


# ---------------------------------------------------------------------------
# Theme preview (live full-screen recolor)
# ---------------------------------------------------------------------------

class TestThemePreview(TestBrowseTui):
    """Preview colors change with cursor position."""

    def _make_dark_theme(self):
        return _make_theme("Dark")

    def _make_light_theme(self):
        return Theme(
            name="Light",
            background=(240, 240, 240),
            foreground=(30, 30, 30),
            black=(0, 0, 0), red=(200, 0, 0), green=(0, 150, 0),
            yellow=(180, 150, 0), blue=(0, 0, 200), purple=(120, 0, 120),
            cyan=(0, 150, 150), white=(220, 220, 220),
            bright_black=(100, 100, 100), bright_red=(255, 80, 80),
            bright_green=(80, 200, 80), bright_yellow=(220, 200, 80),
            bright_blue=(80, 80, 255), bright_purple=(200, 80, 200),
            bright_cyan=(80, 200, 200), bright_white=(255, 255, 255),
        )

    def test_background_uses_cursor_theme(self):
        """Screen bg escape matches cursor theme's background."""
        themes = [self._make_dark_theme(), self._make_light_theme()]
        output = self._run_tui(themes, "q")
        # Dark theme bg (0,0,0) is selected initially
        assert "\033[48;2;0;0;0m" in output

    def test_foreground_uses_cursor_theme(self):
        """Screen fg escape matches cursor theme's foreground."""
        themes = [self._make_dark_theme(), self._make_light_theme()]
        output = self._run_tui(themes, "q")
        # Dark theme fg (255,255,255)
        assert "\033[38;2;255;255;255m" in output

    def test_moving_cursor_changes_preview(self):
        """Moving down switches preview to second theme's colors."""
        themes = [self._make_dark_theme(), self._make_light_theme()]
        # Down arrow then quit
        output = self._run_tui(themes, "\033[Bq")
        # Light theme bg (240,240,240) should appear after move
        assert "\033[48;2;240;240;240m" in output


# ---------------------------------------------------------------------------
# browse_themes entry point
# ---------------------------------------------------------------------------

class TestBrowseThemes:
    def test_empty_themes(self, capsys):
        """No themes available prints message."""
        with mock.patch("clippy.theme_browser.load_all_themes", return_value=[]):
            browse_themes()
        err = capsys.readouterr().err
        assert "No themes" in err

    def test_falls_back_to_simple_when_no_tty(self, capsys):
        """Falls back to simple list when stdin is not a tty."""
        themes = [_make_theme("Alpha")]
        with mock.patch("clippy.theme_browser.load_all_themes", return_value=themes), \
             mock.patch("clippy.theme_browser.get_active_theme_name", return_value=None), \
             mock.patch("sys.stdin") as mock_stdin, \
             mock.patch("builtins.input", return_value="q"):
            mock_stdin.isatty.return_value = False
            browse_themes()
        out = capsys.readouterr().out
        assert "Alpha" in out


# ---------------------------------------------------------------------------
# ANSI-aware string helpers
# ---------------------------------------------------------------------------

class TestAnsiHelpers:
    def test_visible_len_strips_ansi(self):
        assert _visible_len("\033[31mhello\033[0m") == 5

    def test_visible_len_plain(self):
        assert _visible_len("hello") == 5

    def test_visible_len_empty(self):
        assert _visible_len("") == 0

    def test_truncate_ansi_respects_width(self):
        s = "\033[31mhello world\033[0m"
        result = _truncate_ansi(s, 5)
        assert _visible_len(result) == 5
        # Escape still present
        assert "\033[31m" in result
        # Only "hello" visible
        assert "hello" in result
        assert "world" not in result

    def test_truncate_ansi_no_truncation(self):
        s = "\033[31mhi\033[0m"
        assert _truncate_ansi(s, 10) == s

    def test_pad_ansi_fills_to_width(self):
        bg = "\033[48;2;0;0;0m"
        s = "\033[31mhi\033[0m"
        result = _pad_ansi(s, 10, bg)
        assert _visible_len(result) == 10

    def test_pad_ansi_truncates_when_over(self):
        bg = "\033[48;2;0;0;0m"
        s = "hello world"
        result = _pad_ansi(s, 5, bg)
        assert _visible_len(result) == 5


# ---------------------------------------------------------------------------
# Code preview panel
# ---------------------------------------------------------------------------

class TestCodePreview(TestBrowseTui):
    """Tests for the syntax-highlighted code preview panel."""

    def test_preview_appears_wide_terminal(self):
        """At 140 cols, output contains highlighted code tokens."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q", term_size=(140, 30))
        # Preview header
        assert "Preview" in output
        # Code from _RIGHT should appear (keywords, imports)
        assert "import" in output
        assert "class" in output or "def" in output

    def test_preview_hidden_narrow_terminal(self):
        """At 80 cols, no preview separator appears."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q", term_size=(80, 24))
        assert "Preview" not in output

    def test_preview_colors_change_on_navigate(self):
        """Moving cursor changes syntax highlight colors in preview."""
        dark = _make_theme("Dark")
        light = Theme(
            name="Light",
            background=(240, 240, 240),
            foreground=(30, 30, 30),
            black=(0, 0, 0), red=(200, 0, 0), green=(0, 150, 0),
            yellow=(180, 150, 0), blue=(0, 0, 200), purple=(120, 0, 120),
            cyan=(0, 150, 150), white=(220, 220, 220),
            bright_black=(100, 100, 100), bright_red=(255, 80, 80),
            bright_green=(80, 200, 80), bright_yellow=(220, 200, 80),
            bright_blue=(80, 80, 255), bright_purple=(200, 80, 200),
            bright_cyan=(80, 200, 200), bright_white=(255, 255, 255),
        )
        # First draw at Dark, then arrow down to Light, then quit
        output = self._run_tui([dark, light], "\033[Bq", term_size=(140, 30))
        # Light theme bg (240,240,240) should appear in preview area
        assert "\033[48;2;240;240;240m" in output

    def test_preview_uses_cr_lf(self):
        """Raw mode \\r\\n requirement holds with preview enabled."""
        themes = [_make_theme("Alpha"), _make_theme("Beta")]
        output = self._run_tui(themes, "q", term_size=(140, 30))
        lines_with_bare_lf = []
        for i, ch in enumerate(output):
            if ch == "\n" and (i == 0 or output[i - 1] != "\r"):
                start = max(0, i - 30)
                end = min(len(output), i + 10)
                lines_with_bare_lf.append(repr(output[start:end]))
        assert lines_with_bare_lf == [], (
            f"Found bare \\n (no \\r) in TUI output at: {lines_with_bare_lf[:3]}"
        )
