"""Theme system — data model, palette generation, and persistence.

Themes follow the standard terminal color scheme JSON format (18 named RGB colors).
They drive both the tattoy palette.toml and the demo-mode IDE appearance.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for RGB tuples (0-255 per channel)
RGB = tuple[int, int, int]

# ---------------------------------------------------------------------------
# Theme dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Theme:
    """Terminal color theme (18 named RGB colors in standard JSON format)."""
    name: str
    background: RGB
    foreground: RGB
    black: RGB          # ANSI 0
    red: RGB            # ANSI 1
    green: RGB          # ANSI 2
    yellow: RGB         # ANSI 3
    blue: RGB           # ANSI 4
    purple: RGB         # ANSI 5
    cyan: RGB           # ANSI 6
    white: RGB          # ANSI 7
    bright_black: RGB   # ANSI 8
    bright_red: RGB     # ANSI 9
    bright_green: RGB   # ANSI 10
    bright_yellow: RGB  # ANSI 11
    bright_blue: RGB    # ANSI 12
    bright_purple: RGB  # ANSI 13
    bright_cyan: RGB    # ANSI 14
    bright_white: RGB   # ANSI 15
    cursor_color: RGB | None = None
    selection_background: RGB | None = None


# ---------------------------------------------------------------------------
# Hex/RGB helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> RGB:
    """Convert '#RRGGBB' hex string to (R, G, B) tuple."""
    h = h.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: #{h}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: RGB) -> str:
    """Convert (R, G, B) tuple to '#RRGGBB' hex string."""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


# ---------------------------------------------------------------------------
# Color scheme JSON parsing
# ---------------------------------------------------------------------------

# Maps color scheme JSON keys to Theme field names
_THEME_KEY_MAP = {
    "name": "name",
    "background": "background",
    "foreground": "foreground",
    "black": "black",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "blue": "blue",
    "purple": "purple",
    "cyan": "cyan",
    "white": "white",
    "brightBlack": "bright_black",
    "brightRed": "bright_red",
    "brightGreen": "bright_green",
    "brightYellow": "bright_yellow",
    "brightBlue": "bright_blue",
    "brightPurple": "bright_purple",
    "brightCyan": "bright_cyan",
    "brightWhite": "bright_white",
    "cursorColor": "cursor_color",
    "selectionBackground": "selection_background",
}

# Required color scheme JSON keys (must all be present)
_THEME_REQUIRED = {
    "name", "background", "foreground",
    "black", "red", "green", "yellow", "blue", "purple", "cyan", "white",
    "brightBlack", "brightRed", "brightGreen", "brightYellow",
    "brightBlue", "brightPurple", "brightCyan", "brightWhite",
}


def parse_theme_json(data: dict[str, Any]) -> Theme:
    """Parse a terminal color scheme JSON object into a Theme.

    Raises ValueError if required fields are missing or colors are malformed.
    """
    missing = _THEME_REQUIRED - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}")

    kwargs: dict[str, Any] = {}
    for json_key, field_name in _THEME_KEY_MAP.items():
        value = data.get(json_key)
        if value is None:
            continue
        if field_name == "name":
            kwargs["name"] = str(value)
        else:
            kwargs[field_name] = _hex_to_rgb(value)
    return Theme(**kwargs)


def theme_to_json(theme: Theme) -> dict[str, Any]:
    """Convert a Theme to color scheme JSON format."""
    # Invert the key map
    field_to_json = {v: k for k, v in _THEME_KEY_MAP.items()}
    result: dict[str, Any] = {}
    for f in fields(theme):
        json_key = field_to_json.get(f.name)
        if json_key is None:
            continue
        value = getattr(theme, f.name)
        if value is None:
            continue
        if f.name == "name":
            result[json_key] = value
        else:
            result[json_key] = _rgb_to_hex(value)
    return result


# ---------------------------------------------------------------------------
# Palette TOML generation
# ---------------------------------------------------------------------------

# Standard xterm 6x6x6 color cube levels
_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def _xterm_cube_color(index: int) -> RGB:
    """Standard xterm color for indices 16-231 (6x6x6 cube)."""
    i = index - 16
    r = _CUBE_LEVELS[i // 36]
    g = _CUBE_LEVELS[(i % 36) // 6]
    b = _CUBE_LEVELS[i % 6]
    return (r, g, b)


def _xterm_grayscale_color(index: int) -> RGB:
    """Standard xterm grayscale for indices 232-255."""
    v = 8 + (index - 232) * 10
    return (v, v, v)


def theme_to_palette_toml(theme: Theme) -> str:
    """Generate tattoy palette.toml content from a Theme.

    Produces 258 entries: ANSI 0-15 from theme, 16-231 standard xterm cube,
    232-255 standard grayscale, plus foreground and background.
    """
    # ANSI 0-15 mapping
    ansi_colors = [
        theme.black, theme.red, theme.green, theme.yellow,
        theme.blue, theme.purple, theme.cyan, theme.white,
        theme.bright_black, theme.bright_red, theme.bright_green,
        theme.bright_yellow, theme.bright_blue, theme.bright_purple,
        theme.bright_cyan, theme.bright_white,
    ]

    lines: list[str] = []

    # ANSI 0-15
    for i, color in enumerate(ansi_colors):
        lines.append(f"{i} = [{color[0]}, {color[1]}, {color[2]}]")

    # xterm cube 16-231
    for i in range(16, 232):
        c = _xterm_cube_color(i)
        lines.append(f"{i} = [{c[0]}, {c[1]}, {c[2]}]")

    # grayscale 232-255
    for i in range(232, 256):
        c = _xterm_grayscale_color(i)
        lines.append(f"{i} = [{c[0]}, {c[1]}, {c[2]}]")

    # foreground and background
    lines.append(
        f"foreground = [{theme.foreground[0]}, {theme.foreground[1]}, {theme.foreground[2]}]"
    )
    lines.append(
        f"background = [{theme.background[0]}, {theme.background[1]}, {theme.background[2]}]"
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# DemoTheme — ANSI escape strings for demo mode IDE rendering
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DemoTheme:
    """ANSI color strings for the demo-mode IDE appearance."""
    ide_bg: str    # editor background
    ide_fg: str    # muted code text
    bar_bg: str    # title/tab bars
    stat_bg: str   # status bar background
    stat_fg: str   # status bar text
    term_bg: str   # terminal panel
    sep_fg: str    # separator characters
    kw_fg: str     # keywords
    str_fg: str    # string literals
    cmt_fg: str    # comments
    func_fg: str   # function names
    num_fg: str    # number literals
    code_fg: str   # default code text


def _fg(r: int, g: int, b: int) -> str:
    """Build ANSI 24-bit foreground escape."""
    return f"\033[38;2;{r};{g};{b}m"


def _bg(r: int, g: int, b: int) -> str:
    """Build ANSI 24-bit background escape."""
    return f"\033[48;2;{r};{g};{b}m"


def _lighten(rgb: RGB, pct: float) -> RGB:
    """Lighten an RGB color toward white by a percentage (0.0-1.0)."""
    return (
        min(255, int(rgb[0] + (255 - rgb[0]) * pct)),
        min(255, int(rgb[1] + (255 - rgb[1]) * pct)),
        min(255, int(rgb[2] + (255 - rgb[2]) * pct)),
    )


def _darken(rgb: RGB, pct: float) -> RGB:
    """Darken an RGB color toward black by a percentage (0.0-1.0)."""
    return (
        max(0, int(rgb[0] * (1 - pct))),
        max(0, int(rgb[1] * (1 - pct))),
        max(0, int(rgb[2] * (1 - pct))),
    )


def _midpoint(a: RGB, b: RGB) -> RGB:
    """Average two RGB colors."""
    return (
        (a[0] + b[0]) // 2,
        (a[1] + b[1]) // 2,
        (a[2] + b[2]) // 2,
    )


def theme_to_demo_theme(theme: Theme) -> DemoTheme:
    """Derive demo-mode IDE colors from a Theme."""
    bar = _lighten(theme.background, 0.05)
    term = _darken(theme.background, 0.03)
    sep = _midpoint(theme.background, theme.foreground)

    return DemoTheme(
        ide_bg=_bg(*theme.background),
        ide_fg=_fg(*theme.bright_black),
        bar_bg=_bg(*bar),
        stat_bg=_bg(*theme.blue),
        stat_fg=_fg(*theme.bright_white),
        term_bg=_bg(*term),
        sep_fg=_fg(*sep),
        kw_fg=_fg(*theme.purple),
        str_fg=_fg(*theme.yellow),
        cmt_fg=_fg(*theme.green),
        func_fg=_fg(*theme.bright_yellow),
        num_fg=_fg(*theme.bright_green),
        code_fg=_fg(*theme.foreground),
    )


def default_demo_theme() -> DemoTheme:
    """Return the original hardcoded VS Code dark+ demo colors."""
    return DemoTheme(
        ide_bg="\033[48;2;24;24;36m",
        ide_fg="\033[38;2;106;118;142m",
        bar_bg="\033[48;2;37;37;52m",
        stat_bg="\033[48;2;0;100;160m",
        stat_fg="\033[38;2;220;230;240m",
        term_bg="\033[48;2;20;20;30m",
        sep_fg="\033[38;2;60;65;80m",
        kw_fg="\033[38;2;197;134;192m",
        str_fg="\033[38;2;206;145;120m",
        cmt_fg="\033[38;2;106;153;85m",
        func_fg="\033[38;2;220;220;170m",
        num_fg="\033[38;2;181;206;168m",
        code_fg="\033[38;2;212;212;212m",
    )


# ---------------------------------------------------------------------------
# Default theme (Tokyo Night)
# ---------------------------------------------------------------------------

def default_theme() -> Theme:
    """Return the built-in Tokyo Night theme."""
    return Theme(
        name="Tokyo Night",
        background=(14, 13, 21),
        foreground=(169, 177, 214),
        black=(14, 13, 21),
        red=(247, 118, 142),
        green=(158, 206, 106),
        yellow=(224, 175, 104),
        blue=(122, 162, 247),
        purple=(173, 142, 230),
        cyan=(68, 157, 171),
        white=(120, 124, 153),
        bright_black=(68, 75, 106),
        bright_red=(255, 122, 147),
        bright_green=(185, 242, 124),
        bright_yellow=(255, 158, 100),
        bright_blue=(125, 166, 255),
        bright_purple=(187, 154, 247),
        bright_cyan=(13, 185, 215),
        bright_white=(172, 176, 208),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    """Return the Clippy's Revenge cache directory."""
    return Path.home() / ".cache" / "clippys-revenge"


def _themes_dir() -> Path:
    """Return the user-imported themes directory."""
    return _cache_dir() / "themes"


def get_active_theme_name() -> str | None:
    """Read the persisted active theme name, or None if unset."""
    theme_file = _cache_dir() / "theme.json"
    if not theme_file.exists():
        return None
    try:
        data = json.loads(theme_file.read_text())
        return data.get("name")
    except (json.JSONDecodeError, OSError):
        return None


def set_active_theme_name(name: str | None) -> None:
    """Persist the active theme name (or clear it with None)."""
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    theme_file = cache / "theme.json"
    if name is None:
        theme_file.unlink(missing_ok=True)
    else:
        theme_file.write_text(json.dumps({"name": name}) + "\n")


def load_bundled_themes() -> list[Theme]:
    """Load the bundled curated themes from themes_data.json."""
    data_path = Path(__file__).parent / "themes_data.json"
    if not data_path.exists():
        return []
    try:
        data = json.loads(data_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load bundled themes: %s", e)
        return []
    themes: list[Theme] = []
    for entry in data:
        try:
            themes.append(parse_theme_json(entry))
        except (ValueError, KeyError) as e:
            logger.warning("Skipping bundled theme: %s", e)
    return themes


def load_user_themes() -> list[Theme]:
    """Load user-imported themes from ~/.cache/clippys-revenge/themes/."""
    themes_dir = _themes_dir()
    if not themes_dir.is_dir():
        return []
    themes: list[Theme] = []
    for path in sorted(themes_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            themes.append(parse_theme_json(data))
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning("Skipping %s: %s", path.name, e)
    return themes


def save_user_theme(theme: Theme) -> Path:
    """Save a theme to the user themes directory. Returns the file path."""
    themes_dir = _themes_dir()
    themes_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in theme.name)
    path = themes_dir / f"{safe_name}.json"
    path.write_text(json.dumps(theme_to_json(theme), indent=2) + "\n")
    return path


def load_all_themes() -> list[Theme]:
    """Load bundled + user themes, deduplicating by name (user wins)."""
    bundled = load_bundled_themes()
    user = load_user_themes()
    seen: set[str] = set()
    result: list[Theme] = []
    # User themes take priority
    for t in user:
        key = t.name.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    for t in bundled:
        key = t.name.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def find_theme(name: str) -> Theme | None:
    """Find a theme by name (case-insensitive). Returns None if not found."""
    target = name.lower()
    for theme in load_all_themes():
        if theme.name.lower() == target:
            return theme
    return None


def get_active_theme() -> Theme | None:
    """Load the currently active theme, or None if default."""
    name = get_active_theme_name()
    if name is None:
        return None
    return find_theme(name)


def apply_theme(theme: Theme, config_dir: str | None = None) -> None:
    """Apply a theme: generate palette.toml and persist the choice."""
    if config_dir is None:
        config_dir = str(_cache_dir())
    out_dir = Path(config_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "palette.toml").write_text(theme_to_palette_toml(theme))
    set_active_theme_name(theme.name)


def import_theme_from_file(path: str) -> Theme:
    """Import a theme from a local JSON file. Raises on invalid input."""
    data = json.loads(Path(path).read_text())
    theme = parse_theme_json(data)
    save_user_theme(theme)
    return theme


def import_theme_from_url(url: str) -> Theme:
    """Import a theme from a URL. Raises on network/parse errors."""
    from urllib.request import urlopen, Request
    req = Request(url, headers={"User-Agent": "ClippysRevenge/1.0"})
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    theme = parse_theme_json(data)
    save_user_theme(theme)
    return theme
