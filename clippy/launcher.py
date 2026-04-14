"""Clippy's Revenge launcher — CLI entry point.

Discovers effects, generates tattoy config, and either lists effects,
runs demo mode, or execs tattoy with the selected effect(s).
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI colour constants
# ---------------------------------------------------------------------------

_GOLD = "\033[38;2;255;200;0m"
_SKY = "\033[38;2;100;180;255m"
_GREEN = "\033[38;2;80;200;80m"
_AMBER = "\033[38;2;220;160;40m"
_ORANGE = "\033[38;2;255;140;0m"
_RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Mascot face (static, ^-eyes variant for CLI messages)
# ---------------------------------------------------------------------------

_FACE_LINES = [
    "╭──╮",
    "^╭╮^",
    "││╰╯",
    "│╰─╯",
    "╰──╯",
]


def _print_clippy_message(
    headline: str,
    body_lines: list[str],
    file=None,
) -> None:
    """Render the mascot face alongside a speech-bubble message.

    *file* can be a writable file object (default: sys.stderr) or a list,
    in which case formatted lines are appended to the list instead of printed.
    """
    if file is None:
        file = sys.stderr
    max_body = max((len(line) for line in body_lines), default=0)
    # W = total bubble width; +6 guarantees at least one ─ before ╮
    W = max(max_body + 4, len(headline) + 6)
    pad = W - 4  # content area for mid lines

    top    = "╭─ " + headline + " " + "─" * (W - len(headline) - 5) + "╮"
    bottom = "╰" + "─" * (W - 2) + "╯"
    mid = [f"│ {line:<{pad}} │" for line in body_lines]

    bubble = [top] + mid + [bottom]

    face_count = len(_FACE_LINES)
    total = max(face_count, len(bubble))

    for i in range(total):
        face_part = _FACE_LINES[i] if i < face_count else " " * len(_FACE_LINES[0])
        bubble_part = bubble[i] if i < len(bubble) else ""
        line = f"  {face_part}  {bubble_part}"
        if isinstance(file, list):
            file.append(line)
        else:
            print(line, file=file)


def find_tattoy() -> str | None:
    """Locate the tattoy binary. Returns absolute path or None."""
    result = shutil.which("tattoy")
    if result:
        return result
    cargo_path = Path.home() / ".cargo" / "bin" / "tattoy"
    if cargo_path.is_file() and os.access(cargo_path, os.X_OK):
        return str(cargo_path)
    return None


def ensure_executable(path: Path) -> None:
    """Add shebang if missing and set +x. Idempotent."""
    try:
        content = path.read_text()
        if not content.startswith("#!"):
            path.write_text("#!/usr/bin/env python3\n" + content)
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as e:
        print(f"clippy: could not make {path} executable: {e}", file=sys.stderr)


def _escape_toml_string(s: str) -> str:
    """Escape a string for safe interpolation into a TOML quoted value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_maturin() -> str | None:
    """Find the maturin binary on PATH or in common locations."""
    result = shutil.which("maturin")
    if result:
        return result
    user_bin = Path.home() / ".local" / "bin" / "maturin"
    if user_bin.is_file() and os.access(user_bin, os.X_OK):
        return str(user_bin)
    return None


def _try_build_native() -> bool:
    """Auto-detect Rust and build the native module if possible.

    Returns True if clippy_native is importable after this call.
    Fails silently on any error — the pure-Python fallback is always available.
    """
    try:
        import clippy_native  # noqa: F401
        return True
    except ImportError:
        pass

    if not shutil.which("cargo"):
        return False

    native_dir = Path(__file__).resolve().parent.parent / "native"
    if not (native_dir / "Cargo.toml").is_file():
        return False

    maturin = _find_maturin()
    if not maturin:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "maturin"],
                capture_output=True, timeout=60, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        maturin = _find_maturin()
        if not maturin:
            return False

    print("Building Rust acceleration module (one-time setup)...", file=sys.stderr)
    try:
        subprocess.run(
            [maturin, "build", "--release", "-i", sys.executable],
            cwd=str(native_dir), capture_output=True, timeout=180, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        print("  Build failed — continuing in pure Python mode.", file=sys.stderr)
        return False

    # Find the most recently built wheel and install it
    wheels_dir = native_dir / "target" / "wheels"
    wheels = sorted(wheels_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        return False

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--force-reinstall", str(wheels[0])],
            capture_output=True, timeout=60, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return False

    # Retry import with fresh caches
    importlib.invalidate_caches()
    sys.modules.pop("clippy_native", None)
    try:
        import clippy_native  # noqa: F401, F811
        print("  Done! Rust acceleration active.", file=sys.stderr)
        return True
    except ImportError:
        return False


def _show_startup(
    selected_names: list[str],
    selectable: dict[str, dict],
    using_native: bool,
    no_toast: bool,
) -> None:
    """Print colour-coded startup banner with animated loading bar to stderr."""
    if selected_names:
        names_str = ", ".join(f"{_SKY}{n}{_RESET}" for n in selected_names)
        print(
            f"{_GOLD}Clippy's Revenge{_RESET} — effects: {names_str}",
            file=sys.stderr,
        )
    else:
        names_str = ", ".join(f"{_SKY}{n}{_RESET}" for n in sorted(selectable))
        print(
            f"{_GOLD}Clippy's Revenge{_RESET} — cycling: {names_str}",
            file=sys.stderr,
        )

    if not no_toast:
        if using_native:
            print(f"  {_GREEN}Rust-optimised mode{_RESET}", file=sys.stderr)
        else:
            print(
                f"  {_AMBER}Pure Python mode{_RESET} — see README.md for Rust acceleration",
                file=sys.stderr,
            )

    sys.stderr.write("  Preparing chaos...\n")
    print(f"  Press {_SKY}ALT+T{_RESET} to toggle effects on/off", file=sys.stderr)
    sys.stderr.flush()


def _parse_effect_names(raw: str, valid_names: set[str]) -> tuple[list[str], list[str]]:
    """Parse comma-separated effect names, dedup preserving order.

    Returns (valid, invalid) lists.
    """
    seen: set[str] = set()
    valid: list[str] = []
    invalid: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        if name in valid_names:
            valid.append(name)
        else:
            invalid.append(name)
    return valid, invalid


def generate_config(
    effect_paths: list[str],
    shell_cmd: str | None = None,
    config_dir: str | None = None,
    theme=None,
) -> str:
    """Generate tattoy.toml (and palette.toml if absent) and return the config dir path.

    config_dir defaults to ~/.cache/clippys-revenge/ (overridable for tests).
    Each path in effect_paths gets its own [[plugins]] block at layer 1.
    If *theme* is a Theme instance, palette.toml is always regenerated from it.
    """
    if shell_cmd is None:
        shell_cmd = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    if config_dir is None:
        config_dir = str(Path.home() / ".cache" / "clippys-revenge")

    out_dir = Path(config_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    toml_content = (
        f'command = "{_escape_toml_string(shell_cmd)}"\n'
        f"frame_rate = 30\n"
        f"show_tattoy_indicator = false\n"
        f"show_startup_logo = false\n"
        f"\n"
        f"[keybindings]\n"
        f'toggle_tattoy = {{ mods = "ALT", key = "t" }}\n'
    )

    for effect_path in effect_paths:
        plugin_name = Path(effect_path).stem
        toml_content += (
            f"\n"
            f"[[plugins]]\n"
            f'name = "{_escape_toml_string(plugin_name)}"\n'
            f'path = "{_escape_toml_string(effect_path)}"\n'
            f"layer = 1\n"
        )

    (out_dir / "tattoy.toml").write_text(toml_content)

    palette_path = out_dir / "palette.toml"
    if theme is not None:
        # Theme provided — always regenerate palette from it
        from clippy.themes import theme_to_palette_toml
        palette_path.write_text(theme_to_palette_toml(theme))
    elif not palette_path.exists():
        # No theme, no existing palette — seed with default
        bundled = Path(__file__).parent / "default_palette.toml"
        palette_path.write_text(bundled.read_text())

    return str(out_dir)


class _ClippyArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that prepends the Clippy mascot to --help."""

    def format_help(self) -> str:
        lines: list[str] = []
        _print_clippy_message(
            "It looks like you're trying to get help!",
            [],
            file=lines,
        )
        lines.append("")
        lines.append(super().format_help())
        return "\n".join(lines)


def _get_version() -> str:
    """Return the package version, falling back to pyproject.toml then 'unknown'."""
    try:
        return importlib.metadata.version("clippys-revenge")
    except importlib.metadata.PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(r'version\s*=\s*"([^"]+)"', pyproject.read_text())
        if m:
            return m.group(1)
    return "unknown"


def _build_parser() -> argparse.ArgumentParser:
    parser = _ClippyArgumentParser(
        prog="clippy",
        description="Clippy's Revenge \u2014 chaotic terminal effects via tattoy",
        epilog="Press ALT+T to toggle effects on/off while running.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument(
        "--effects", "-e",
        metavar="NAMES",
        help="comma-separated effect name(s) (default: cycle all)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="list available effects and exit",
    )
    parser.add_argument(
        "--demo",
        metavar="NAME",
        help="standalone ANSI preview (no tattoy required)",
    )
    parser.add_argument(
        "--optimised",
        choices=["on", "off"],
        default=None,
        help="force Rust acceleration on/off (default: auto-detect)",
    )
    parser.add_argument(
        "--shake",
        metavar="MODE",
        default=None,
        help="cursor-shake detection: 'off' to disable, or an integer sensitivity "
             "(number of reversals needed, default 5; higher = harder to trigger)",
    )
    parser.add_argument(
        "--theme",
        metavar="NAME",
        default=None,
        help="apply a named color theme (persisted for future runs)",
    )
    parser.add_argument(
        "--themes",
        action="store_true",
        help="browse available themes interactively",
    )
    parser.add_argument(
        "--theme-import",
        metavar="PATH",
        default=None,
        help="import a color scheme JSON theme (file path or URL)",
    )
    parser.add_argument(
        "--theme-list",
        action="store_true",
        help="list available theme names and exit",
    )
    parser.add_argument(
        "--theme-reset",
        action="store_true",
        help="reset to default theme (Tokyo Night)",
    )
    parser.add_argument(
        "--startup-pause",
        action="store_true",
        help="pause after startup info and wait for Enter before launching",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="command to wrap (default: $SHELL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI dispatch. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    from clippy.effects import discover_effects
    effects = discover_effects()
    selectable = {k: v for k, v in effects.items() if not v.get("overlay")}
    overlays   = {k: v for k, v in effects.items() if     v.get("overlay")}

    # --list (overlays excluded) — no native build needed
    if args.list:
        if not selectable:
            _print_clippy_message(
                "It looks like you're trying to wreak havoc!",
                ["No effects found."],
                file=sys.stdout,
            )
            return 0
        body = [f"  {name:18s} {meta.get('description', '')}" for name, meta in sorted(selectable.items())]
        _print_clippy_message(
            "It looks like you're trying to pick an effect!",
            body,
            file=sys.stdout,
        )
        return 0

    # --theme-list (early exit, no native build needed)
    if args.theme_list:
        from clippy.themes import load_all_themes
        for t in sorted(load_all_themes(), key=lambda t: t.name.lower()):
            print(t.name)
        return 0

    # --optimised handling
    no_toast = os.environ.get("CLIPPY_NO_TOAST", "").lower() in ("1", "true", "yes")
    force_python = os.environ.get("CLIPPY_FORCE_PYTHON", "").lower() in ("1", "true", "yes")

    if args.optimised == "off":
        using_native = False
    elif args.optimised == "on":
        try:
            import clippy_native  # noqa: F401
            using_native = True
        except ImportError:
            _print_clippy_message(
                "It looks like you're trying to go fast!",
                [
                    "Rust acceleration module not found.",
                    "",
                    "Build it with:",
                    "  pip install maturin",
                    "  cd native && maturin develop --release",
                ],
            )
            return 1
    else:
        using_native = not force_python and _try_build_native()

    # --shake handling
    if args.shake is not None:
        val = args.shake.strip().lower()
        if val == "off":
            os.environ["CLIPPY_SHAKE"] = "off"
        elif val.isdigit() and int(val) > 0:
            os.environ["CLIPPY_SHAKE"] = val
        else:
            _print_clippy_message(
                "It looks like you're trying to configure shake!",
                [f"Invalid --shake value: {args.shake!r}", "", "Use 'off' or a positive integer."],
            )
            return 1

    # --theme-reset
    if args.theme_reset:
        from clippy.themes import set_active_theme_name, default_theme, theme_to_palette_toml
        set_active_theme_name(None)
        # Regenerate palette to default
        cache = Path.home() / ".cache" / "clippys-revenge"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "palette.toml").write_text(
            theme_to_palette_toml(default_theme())
        )
        _print_clippy_message(
            "It looks like you're trying to reset your theme!",
            ["Theme reset to Tokyo Night (default)."],
            file=sys.stdout,
        )
        return 0

    # --theme-import
    if args.theme_import:
        from clippy.themes import (
            apply_theme,
            import_theme_from_file,
            import_theme_from_url,
        )
        source = args.theme_import
        try:
            if source.startswith("http://") or source.startswith("https://"):
                theme_obj = import_theme_from_url(source)
            else:
                theme_obj = import_theme_from_file(source)
        except Exception as e:
            _print_clippy_message(
                "It looks like you're trying to import a theme!",
                [f"Failed to import theme: {e}"],
            )
            return 1
        apply_theme(theme_obj)
        _print_clippy_message(
            "It looks like you're trying to import a theme!",
            [f"Imported and applied: {theme_obj.name}"],
            file=sys.stdout,
        )
        return 0

    # --themes (interactive browser)
    if args.themes:
        from clippy.theme_browser import browse_themes
        browse_themes()
        return 0

    # Resolve active theme (from --theme flag or persisted choice)
    active_theme = None
    demo_theme = None
    if args.theme:
        from clippy.themes import find_theme, apply_theme
        active_theme = find_theme(args.theme)
        if active_theme is None:
            from clippy.themes import load_all_themes
            available = [t.name for t in load_all_themes()]
            # Case-insensitive substring matches
            matches = [n for n in available if args.theme.lower() in n.lower()]
            body = [f"Unknown theme: {args.theme}"]
            if matches:
                body += ["", "Did you mean:"]
                body += [f"  {n}" for n in matches[:10]]
            else:
                body += ["", "Use --themes to browse available themes."]
            _print_clippy_message(
                "It looks like you're trying to pick a theme!",
                body,
            )
            return 1
        apply_theme(active_theme)
    else:
        from clippy.themes import get_active_theme
        active_theme = get_active_theme()

    if active_theme is not None:
        from clippy.themes import theme_to_demo_theme
        demo_theme = theme_to_demo_theme(active_theme)

    # --demo (all effects allowed, including overlays)
    if args.demo:
        if args.demo not in effects:
            available = ", ".join(sorted(effects))
            _print_clippy_message(
                "It looks like you're trying to demo an effect!",
                [f"Unknown effect: {args.demo}", "", f"Available: {available}"],
            )
            return 1

        meta = effects[args.demo]
        module = importlib.import_module(f"clippy.effects.{Path(meta['module_path']).stem}")
        effect_class = getattr(module, meta["class_name"])

        if meta.get("overlay"):
            effect = effect_class(idle_secs=0)
        else:
            from clippy.unified import UnifiedEffect
            effect = UnifiedEffect(effect_class, idle_secs=0)

        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols = int(os.environ.get("COLUMNS", 80))
            rows = int(os.environ.get("LINES", 24))

        toast = None
        if not no_toast:
            if using_native:
                toast = "Rust-optimised mode | CLIPPY_NO_TOAST=1 to hide"
            else:
                toast = "Python mode | see README.md for Rust speed | CLIPPY_NO_TOAST=1 to hide"

        from clippy.demo import demo_run
        try:
            demo_run(
                effect, cols, rows,
                toast=toast, toast_is_native=using_native,
                theme=demo_theme,
            )
        except KeyboardInterrupt:
            pass
        return 0

    # Select effect(s) (overlays not selectable)
    selected_names: list[str] = []
    if args.effects:
        valid, invalid = _parse_effect_names(args.effects, set(selectable))

        # Check for overlay names in the invalid list
        overlay_hits = [n for n in invalid if n in overlays]
        if overlay_hits:
            _print_clippy_message(
                "It looks like you're trying to use an overlay!",
                [
                    f"'{', '.join(overlay_hits)}' cannot be used with --effects.",
                    f"Use --demo {overlay_hits[0]} to preview it.",
                ],
            )
            return 1

        if not valid:
            body = [f"Unknown effect(s): {', '.join(invalid)}", ""]
            body += [f"  {n:18s} {m.get('description', '')}" for n, m in sorted(selectable.items())]
            _print_clippy_message(
                "It looks like you're trying to pick effects!",
                body,
            )
            return 1

        if invalid:
            _print_clippy_message(
                "It looks like you made a typo!",
                [f"Ignoring unknown effect(s): {', '.join(invalid)}"],
            )

        selected_names = valid
    else:
        if not selectable:
            _print_clippy_message(
                "It looks like you're trying to wreak havoc!",
                ["No effects found."],
            )
            return 1

    # Require tattoy
    tattoy_path = find_tattoy()
    if tattoy_path is None:
        _print_clippy_message(
            "It looks like you're trying to launch Clippy!",
            [
                "tattoy not found.",
                "",
                "Try demo mode (no tattoy needed):",
                "  clippy --demo fire",
                "",
                "Install tattoy for the full experience:",
                "  https://tattoy.sh",
                "  Or:  cargo install tattoy",
            ],
        )
        return 1

    # Use unified runner as the plugin entry point
    runner_path = str(Path(__file__).resolve().parent / "unified_runner.py")
    ensure_executable(Path(runner_path))

    # Set PYTHONPATH so the effect subprocess can import clippy.*
    project_root = str(Path(__file__).resolve().parent.parent)
    existing = os.environ.get("PYTHONPATH", "")
    if project_root not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = project_root + (os.pathsep + existing if existing else "")

    # Tell unified_runner which effect(s) to use
    os.environ.pop("CLIPPY_EFFECT", None)  # clean up old singular env var
    if selected_names:
        os.environ["CLIPPY_EFFECTS"] = ",".join(selected_names)
    else:
        os.environ.pop("CLIPPY_EFFECTS", None)

    # Build shell command
    shell_cmd = " ".join(args.command) if args.command else None

    # Generate config and launch
    config_path = generate_config(
        effect_paths=[runner_path],
        shell_cmd=shell_cmd,
        theme=active_theme,
    )

    _show_startup(selected_names, selectable, using_native, no_toast)

    if args.startup_pause:
        sys.stderr.write("\n  Press Enter to continue...")
        sys.stderr.flush()
        input()

    os.execvp(tattoy_path, [tattoy_path, "--config-dir", config_path])
    return 0  # unreachable, but keeps the type checker happy


if __name__ == "__main__":
    sys.exit(main())
