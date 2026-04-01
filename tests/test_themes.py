"""Tests for clippy.themes — theme parsing, palette generation, persistence."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from clippy.themes import (
    DemoTheme,
    Theme,
    _darken,
    _hex_to_rgb,
    _lighten,
    _midpoint,
    _rgb_to_hex,
    apply_theme,
    default_demo_theme,
    default_theme,
    find_theme,
    get_active_theme,
    get_active_theme_name,
    import_theme_from_file,
    load_all_themes,
    load_bundled_themes,
    load_user_themes,
    parse_theme_json,
    save_user_theme,
    set_active_theme_name,
    theme_to_demo_theme,
    theme_to_palette_toml,
    theme_to_json,
)


# ---------------------------------------------------------------------------
# Hex / RGB helpers
# ---------------------------------------------------------------------------

class TestHexToRgb:
    def test_basic(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_lowercase(self):
        assert _hex_to_rgb("#00ff00") == (0, 255, 0)

    def test_no_hash(self):
        assert _hex_to_rgb("0000FF") == (0, 0, 255)

    def test_mixed_case(self):
        assert _hex_to_rgb("#aAbBcC") == (170, 187, 204)

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="Invalid hex"):
            _hex_to_rgb("#FFF")


class TestRgbToHex:
    def test_red(self):
        assert _rgb_to_hex((255, 0, 0)) == "#FF0000"

    def test_black(self):
        assert _rgb_to_hex((0, 0, 0)) == "#000000"

    def test_mixed(self):
        assert _rgb_to_hex((10, 20, 30)) == "#0A141E"


# ---------------------------------------------------------------------------
# Color manipulation helpers
# ---------------------------------------------------------------------------

class TestColorHelpers:
    def test_lighten_black(self):
        assert _lighten((0, 0, 0), 0.5) == (127, 127, 127)

    def test_lighten_zero(self):
        assert _lighten((100, 100, 100), 0.0) == (100, 100, 100)

    def test_lighten_full(self):
        assert _lighten((100, 100, 100), 1.0) == (255, 255, 255)

    def test_darken_white(self):
        assert _darken((255, 255, 255), 0.5) == (127, 127, 127)

    def test_darken_zero(self):
        assert _darken((100, 100, 100), 0.0) == (100, 100, 100)

    def test_darken_full(self):
        assert _darken((100, 100, 100), 1.0) == (0, 0, 0)

    def test_midpoint(self):
        assert _midpoint((0, 0, 0), (100, 200, 50)) == (50, 100, 25)

    def test_midpoint_symmetric(self):
        a, b = (10, 20, 30), (40, 50, 60)
        assert _midpoint(a, b) == _midpoint(b, a)


# ---------------------------------------------------------------------------
# Color scheme JSON parsing
# ---------------------------------------------------------------------------

def _make_theme_json(**overrides) -> dict:
    """Build a minimal valid color scheme JSON object."""
    base = {
        "name": "Test Theme",
        "background": "#1A1B26",
        "foreground": "#A9B1D6",
        "black": "#0E0D15",
        "red": "#F7768E",
        "green": "#9ECE6A",
        "yellow": "#E0AF68",
        "blue": "#7AA2F7",
        "purple": "#AD8EE6",
        "cyan": "#449DAB",
        "white": "#787C99",
        "brightBlack": "#444B6A",
        "brightRed": "#FF7A93",
        "brightGreen": "#B9F27C",
        "brightYellow": "#FF9E64",
        "brightBlue": "#7DA6FF",
        "brightPurple": "#BB9AF7",
        "brightCyan": "#0DB9D7",
        "brightWhite": "#ACB0D0",
    }
    base.update(overrides)
    return base


class TestParseThemeJson:
    def test_valid_roundtrip(self):
        data = _make_theme_json()
        theme = parse_theme_json(data)
        assert theme.name == "Test Theme"
        assert theme.background == (26, 27, 38)
        assert theme.red == (247, 118, 142)

    def test_missing_required_field(self):
        data = _make_theme_json()
        del data["red"]
        with pytest.raises(ValueError, match="Missing required"):
            parse_theme_json(data)

    def test_optional_cursor_color(self):
        data = _make_theme_json(cursorColor="#FFFFFF")
        theme = parse_theme_json(data)
        assert theme.cursor_color == (255, 255, 255)

    def test_optional_selection_bg(self):
        data = _make_theme_json(selectionBackground="#333333")
        theme = parse_theme_json(data)
        assert theme.selection_background == (51, 51, 51)

    def test_missing_optional_is_none(self):
        theme = parse_theme_json(_make_theme_json())
        assert theme.cursor_color is None
        assert theme.selection_background is None


class TestThemeToJson:
    def test_roundtrip(self):
        data = _make_theme_json()
        theme = parse_theme_json(data)
        result = theme_to_json(theme)
        assert result["name"] == "Test Theme"
        assert result["background"] == "#1A1B26"
        assert result["brightRed"] == "#FF7A93"

    def test_optional_omitted_when_none(self):
        theme = parse_theme_json(_make_theme_json())
        result = theme_to_json(theme)
        assert "cursorColor" not in result
        assert "selectionBackground" not in result


# ---------------------------------------------------------------------------
# Default theme
# ---------------------------------------------------------------------------

class TestDefaultTheme:
    def test_name(self):
        assert default_theme().name == "Tokyo Night"

    def test_background(self):
        assert default_theme().background == (14, 13, 21)

    def test_foreground(self):
        assert default_theme().foreground == (169, 177, 214)

    def test_all_colors_valid_rgb(self):
        theme = default_theme()
        for f in [
            "black", "red", "green", "yellow", "blue", "purple", "cyan", "white",
            "bright_black", "bright_red", "bright_green", "bright_yellow",
            "bright_blue", "bright_purple", "bright_cyan", "bright_white",
            "foreground", "background",
        ]:
            rgb = getattr(theme, f)
            assert len(rgb) == 3
            assert all(0 <= v <= 255 for v in rgb), f"{f} has out-of-range values: {rgb}"


# ---------------------------------------------------------------------------
# Palette generation
# ---------------------------------------------------------------------------

class TestPaletteToml:
    def test_roundtrip_matches_default_palette(self):
        """Generated palette from default_theme() matches default_palette.toml."""
        generated = theme_to_palette_toml(default_theme())
        bundled = (Path(__file__).parent.parent / "clippy" / "default_palette.toml").read_text()
        assert generated == bundled

    def test_line_count(self):
        toml = theme_to_palette_toml(default_theme())
        lines = [l for l in toml.strip().split("\n") if l]
        assert len(lines) == 258  # 256 colors + fg + bg

    def test_ansi_0_is_black(self):
        toml = theme_to_palette_toml(default_theme())
        assert "0 = [14, 13, 21]" in toml

    def test_xterm_cube_standard(self):
        """Entries 16-231 use standard xterm 6x6x6 cube."""
        toml = theme_to_palette_toml(default_theme())
        # Index 196 = pure red in xterm cube: rgb(255, 0, 0)
        assert "196 = [255, 0, 0]" in toml
        # Index 21 = pure blue: rgb(0, 0, 255)
        assert "21 = [0, 0, 255]" in toml

    def test_grayscale_ramp(self):
        """Entries 232-255 use standard grayscale."""
        toml = theme_to_palette_toml(default_theme())
        assert "232 = [8, 8, 8]" in toml
        assert "255 = [238, 238, 238]" in toml

    def test_foreground_background(self):
        toml = theme_to_palette_toml(default_theme())
        assert "foreground = [169, 177, 214]" in toml
        assert "background = [14, 13, 21]" in toml

    def test_different_theme_changes_ansi(self):
        """A different theme produces different ANSI 0-15 values."""
        theme = default_theme()
        theme2 = Theme(
            name="Custom",
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
        toml1 = theme_to_palette_toml(theme)
        toml2 = theme_to_palette_toml(theme2)
        # ANSI colors differ
        assert toml1.split("\n")[0] != toml2.split("\n")[0]
        # But xterm cube stays the same (line index 16 = index 16)
        assert toml1.split("\n")[16] == toml2.split("\n")[16]


# ---------------------------------------------------------------------------
# DemoTheme
# ---------------------------------------------------------------------------

class TestDemoTheme:
    def test_default_preserves_hardcoded(self):
        """default_demo_theme() returns the exact original VS Code colors."""
        dt = default_demo_theme()
        assert dt.ide_bg == "\033[48;2;24;24;36m"
        assert dt.ide_fg == "\033[38;2;106;118;142m"
        assert dt.bar_bg == "\033[48;2;37;37;52m"
        assert dt.stat_bg == "\033[48;2;0;100;160m"
        assert dt.stat_fg == "\033[38;2;220;230;240m"
        assert dt.term_bg == "\033[48;2;20;20;30m"
        assert dt.sep_fg == "\033[38;2;60;65;80m"
        assert dt.kw_fg == "\033[38;2;197;134;192m"
        assert dt.str_fg == "\033[38;2;206;145;120m"
        assert dt.cmt_fg == "\033[38;2;106;153;85m"
        assert dt.func_fg == "\033[38;2;220;220;170m"
        assert dt.num_fg == "\033[38;2;181;206;168m"
        assert dt.code_fg == "\033[38;2;212;212;212m"

    def test_theme_to_demo_returns_demotheme(self):
        dt = theme_to_demo_theme(default_theme())
        assert isinstance(dt, DemoTheme)

    def test_all_fields_are_ansi_escapes(self):
        dt = theme_to_demo_theme(default_theme())
        for field_name in [
            "ide_bg", "ide_fg", "bar_bg", "stat_bg", "stat_fg",
            "term_bg", "sep_fg", "kw_fg", "str_fg", "cmt_fg",
            "func_fg", "num_fg", "code_fg",
        ]:
            val = getattr(dt, field_name)
            assert val.startswith("\033["), f"{field_name} is not an ANSI escape: {val!r}"

    def test_derived_uses_theme_colors(self):
        """Derived theme uses the theme's ANSI colors."""
        theme = Theme(
            name="Bright",
            background=(10, 10, 10),
            foreground=(200, 200, 200),
            black=(0, 0, 0), red=(255, 0, 0), green=(0, 255, 0),
            yellow=(255, 255, 0), blue=(0, 0, 255), purple=(128, 0, 128),
            cyan=(0, 255, 255), white=(192, 192, 192),
            bright_black=(80, 80, 80), bright_red=(255, 128, 128),
            bright_green=(128, 255, 128), bright_yellow=(255, 255, 128),
            bright_blue=(128, 128, 255), bright_purple=(255, 128, 255),
            bright_cyan=(128, 255, 255), bright_white=(240, 240, 240),
        )
        dt = theme_to_demo_theme(theme)
        # kw_fg should use theme.purple
        assert "128;0;128" in dt.kw_fg
        # code_fg should use theme.foreground
        assert "200;200;200" in dt.code_fg


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_set_and_get_active_theme(self, tmp_path):
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            set_active_theme_name("Dracula")
            assert get_active_theme_name() == "Dracula"

    def test_get_active_theme_none_default(self, tmp_path):
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            assert get_active_theme_name() is None

    def test_set_none_clears(self, tmp_path):
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            set_active_theme_name("Dracula")
            set_active_theme_name(None)
            assert get_active_theme_name() is None

    def test_corrupted_json_returns_none(self, tmp_path):
        (tmp_path / "theme.json").write_text("not json{{{")
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            assert get_active_theme_name() is None


class TestSaveLoadUserThemes:
    def test_save_and_load(self, tmp_path):
        theme = default_theme()
        with mock.patch("clippy.themes._themes_dir", return_value=tmp_path / "themes"):
            path = save_user_theme(theme)
            assert path.exists()
            loaded = load_user_themes()
            assert len(loaded) == 1
            assert loaded[0].name == "Tokyo Night"

    def test_load_empty_dir(self, tmp_path):
        with mock.patch("clippy.themes._themes_dir", return_value=tmp_path / "nonexistent"):
            assert load_user_themes() == []

    def test_load_skips_invalid(self, tmp_path):
        themes_dir = tmp_path / "themes"
        themes_dir.mkdir()
        (themes_dir / "bad.json").write_text("invalid json")
        with mock.patch("clippy.themes._themes_dir", return_value=themes_dir):
            assert load_user_themes() == []


class TestLoadBundledThemes:
    def test_loads_themes(self):
        themes = load_bundled_themes()
        # Should find at least a few themes once themes_data.json exists
        if (Path(__file__).parent.parent / "clippy" / "themes_data.json").exists():
            assert len(themes) > 0
            names = [t.name for t in themes]
            assert "Tokyo Night" in names


class TestLoadAllThemes:
    def test_user_overrides_bundled(self, tmp_path):
        """User theme with same name takes precedence over bundled."""
        user_theme = Theme(
            name="Tokyo Night",
            background=(0, 0, 0),  # Different from bundled
            foreground=(255, 255, 255),
            black=(0, 0, 0), red=(255, 0, 0), green=(0, 255, 0),
            yellow=(255, 255, 0), blue=(0, 0, 255), purple=(128, 0, 128),
            cyan=(0, 255, 255), white=(192, 192, 192),
            bright_black=(128, 128, 128), bright_red=(255, 128, 128),
            bright_green=(128, 255, 128), bright_yellow=(255, 255, 128),
            bright_blue=(128, 128, 255), bright_purple=(255, 128, 255),
            bright_cyan=(128, 255, 255), bright_white=(255, 255, 255),
        )
        with mock.patch("clippy.themes.load_user_themes", return_value=[user_theme]), \
             mock.patch("clippy.themes.load_bundled_themes", return_value=[default_theme()]):
            all_themes = load_all_themes()
            matching = [t for t in all_themes if t.name == "Tokyo Night"]
            assert len(matching) == 1
            assert matching[0].background == (0, 0, 0)  # user version


class TestApplyTheme:
    def test_generates_palette(self, tmp_path):
        theme = default_theme()
        apply_theme(theme, config_dir=str(tmp_path))
        assert (tmp_path / "palette.toml").exists()

    def test_persists_name(self, tmp_path):
        theme = default_theme()
        with mock.patch("clippy.themes._cache_dir", return_value=tmp_path):
            apply_theme(theme, config_dir=str(tmp_path))
            assert get_active_theme_name() == "Tokyo Night"


class TestImportThemeFromFile:
    def test_import_valid(self, tmp_path):
        data = _make_theme_json(name="My Custom")
        path = tmp_path / "custom.json"
        path.write_text(json.dumps(data))
        with mock.patch("clippy.themes._themes_dir", return_value=tmp_path / "themes"):
            theme = import_theme_from_file(str(path))
            assert theme.name == "My Custom"
            # Should be saved to user themes dir
            assert (tmp_path / "themes" / "My Custom.json").exists()

    def test_import_invalid(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text('{"name": "bad"}')
        with pytest.raises(ValueError):
            import_theme_from_file(str(path))
