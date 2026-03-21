"""Clippy's Revenge launcher — CLI entry point.

Discovers effects, generates tattoy config, and either lists effects,
runs demo mode, or execs tattoy with the selected effect.
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import stat
import sys
from pathlib import Path


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
    content = path.read_text()
    if not content.startswith("#!"):
        path.write_text("#!/usr/bin/env python3\n" + content)
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _escape_toml_string(s: str) -> str:
    """Escape a string for safe interpolation into a TOML quoted value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate_config(
    effect_paths: list[str],
    shell_cmd: str | None = None,
    fps: int = 30,
    config_dir: str | None = None,
) -> str:
    """Generate tattoy.toml (and palette.toml if absent) and return the config dir path.

    config_dir defaults to ~/.cache/clippys-revenge/ (overridable for tests).
    Each path in effect_paths gets its own [[plugins]] block at layer 2.
    """
    if shell_cmd is None:
        shell_cmd = os.environ.get("SHELL", "/bin/bash")
    if config_dir is None:
        config_dir = str(Path.home() / ".cache" / "clippys-revenge")

    out_dir = Path(config_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    toml_content = (
        f'command = "{_escape_toml_string(shell_cmd)}"\n'
        f"frame_rate = {fps}\n"
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
            f"layer = 2\n"
        )

    (out_dir / "tattoy.toml").write_text(toml_content)

    # Pre-seed palette.toml so tattoy skips interactive palette detection.
    # Without this, tattoy prompts the user on first run, which fails in WSL/multiplexers.
    palette_path = out_dir / "palette.toml"
    if not palette_path.exists():
        bundled = Path(__file__).parent / "default_palette.toml"
        palette_path.write_text(bundled.read_text())

    return str(out_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clippy",
        description="Clippy's Revenge — chaotic terminal effects via tattoy",
    )
    parser.add_argument(
        "--effect", "-e",
        metavar="NAME",
        help="effect to use (default: random)",
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
        "--fps",
        type=int,
        default=30,
        help="frame rate (default: 30)",
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

    # --list (overlays excluded)
    if args.list:
        if not selectable:
            print("No effects found.")
            return 0
        for name, meta in sorted(selectable.items()):
            desc = meta.get("description", "")
            print(f"  {name:20s} {desc}")
        return 0

    # --demo (all effects allowed, including overlays)
    if args.demo:
        if args.demo not in effects:
            print(f"Unknown effect: {args.demo}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(effects))}", file=sys.stderr)
            return 1

        meta = effects[args.demo]
        module = importlib.import_module(f"clippy.effects.{Path(meta['module_path']).stem}")
        effect_class = getattr(module, meta["class_name"])

        if meta.get("overlay"):
            # Standalone overlay demo (e.g. --demo mascot)
            effect = effect_class(idle_secs=0)
        else:
            # Wrap in UnifiedEffect for demo mode
            from clippy.unified import UnifiedEffect
            effect = UnifiedEffect(effect_class, idle_secs=0)

        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols = int(os.environ.get("COLUMNS", 80))
            rows = int(os.environ.get("LINES", 24))

        from clippy.demo import demo_run
        try:
            demo_run(effect, cols, rows, fps=args.fps)
        except KeyboardInterrupt:
            pass
        return 0

    # Select effect (overlays not selectable via --effect or random)
    if args.effect:
        if args.effect in overlays:
            print(f"'{args.effect}' is an overlay effect and cannot be used with --effect.", file=sys.stderr)
            print(f"Use --demo {args.effect} to preview it.", file=sys.stderr)
            return 1
        if args.effect not in selectable:
            print(f"Unknown effect: {args.effect}", file=sys.stderr)
            print(f"Available: {', '.join(sorted(selectable))}", file=sys.stderr)
            return 1
        selected = args.effect
    else:
        if not selectable:
            print("No effects found.", file=sys.stderr)
            return 1
        selected = None  # unified_runner will cycle through all effects

    # Require tattoy
    tattoy_path = find_tattoy()
    if tattoy_path is None:
        print("Error: tattoy not found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Install tattoy:  https://tattoy.sh", file=sys.stderr)
        print("  Or:  cargo install tattoy", file=sys.stderr)
        return 1

    # Use unified runner as the plugin entry point
    runner_path = str(Path(__file__).resolve().parent / "unified_runner.py")
    ensure_executable(Path(runner_path))

    # Set PYTHONPATH so the effect subprocess can import clippy.*
    project_root = str(Path(__file__).resolve().parent.parent)
    existing = os.environ.get("PYTHONPATH", "")
    if project_root not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = project_root + (os.pathsep + existing if existing else "")

    # Tell unified_runner which effect to use (if pinned)
    if selected:
        os.environ["CLIPPY_EFFECT"] = selected
    else:
        os.environ.pop("CLIPPY_EFFECT", None)

    # Build shell command
    shell_cmd = " ".join(args.command) if args.command else None

    # Generate config and launch
    config_path = generate_config(
        effect_paths=[runner_path],
        shell_cmd=shell_cmd,
        fps=args.fps,
    )

    if selected:
        print(f"Launching Clippy's Revenge with '{selected}' effect...")
    else:
        print(f"Launching Clippy's Revenge cycling through: {', '.join(sorted(selectable))}...")

    os.execvp(tattoy_path, [tattoy_path, "--config-dir", config_path])
    return 0  # unreachable, but keeps the type checker happy


if __name__ == "__main__":
    sys.exit(main())
