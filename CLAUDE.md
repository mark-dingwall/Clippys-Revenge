# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Clippy's Revenge is a Python plugin system for [tattoy](https://tattoy.sh) (a Rust terminal compositor). Plugins communicate with tattoy via line-delimited JSON on stdin/stdout. The project has zero third-party Python dependencies — stdlib only, Python 3.10+. `pytest` is the sole dev dependency.

## Commands

```bash
# Install dev dependencies
python3 -m pip install -e ".[dev]"

# Run all tests
python3 -m pytest tests/ -v

# Run a single test file
python3 -m pytest tests/test_fire.py -v

# Run a single test by name
python3 -m pytest tests/test_fire.py -k test_coordinates_in_bounds -v

# Regenerate golden files (review diff before committing)
UPDATE_GOLDEN=1 python3 -m pytest tests/test_types.py -v

# Demo mode (no tattoy needed)
python3 -m clippy.launcher --demo fire

# Pick a specific effect
python3 -m clippy.launcher --effects fire

# Custom frame rate (via env var — no --fps flag)
CLIPPY_FPS=60 python3 -m clippy.launcher --demo fire

# Force Rust acceleration on or off
python3 -m clippy.launcher --optimised on

# List effects
python3 -m clippy.launcher --list

# Show version
python3 -m clippy.launcher --version

# Theme commands
python3 -m clippy.launcher --themes              # Browse themes interactively
python3 -m clippy.launcher --theme dracula        # Apply a named theme
python3 -m clippy.launcher --theme-import path.json  # Import a color scheme JSON theme
python3 -m clippy.launcher --theme-list           # List available theme names (non-interactive)
python3 -m clippy.launcher --theme-reset          # Reset to default (Tokyo Night)

# Cursor-shake sensitivity
python3 -m clippy.launcher --shake off            # Disable shake detection
python3 -m clippy.launcher --shake 8              # Require more reversals

# Pause at startup to read diagnostics
python3 -m clippy.launcher --startup-pause

# Build optional Rust acceleration module
pip install maturin
cd native && maturin develop --release

# Force pure-Python path (for testing/debugging)
CLIPPY_FORCE_PYTHON=1 python3 -m pytest tests/ -v
```

Note: Python might be invoked either with `python3` or `python`, depending on the system. Use `which` if you're not sure.

## Architecture

```
User runs `clippy` CLI
  → launcher.py detects tattoy, generates tattoy.toml, execs tattoy
    → tattoy spawns effect plugins as subprocesses
      → each plugin reads JSON from stdin, writes JSON to stdout
```

**Core modules:**

- `clippy/types.py` — Protocol dataclasses (`Cell`, `Pixel`, `PTYUpdate`, `TTYResize`, `OutputText`, `OutputCells`, `OutputPixels`) and JSON serialization. `from_json()` never raises — returns `None` for any malformed input. Also contains `CursorShakeDetector` (detects 5 x-axis reversals within 60 ticks; has `reset()` to clear state at phase boundaries).
- `clippy/harness.py` — `Effect` protocol, `step()` (single-tick test seam), and `run()` (threaded stdin/stdout protocol loop with frame-rate control).
- `clippy/mascot_render.py` — Shared mascot rendering: constants (face geometry, blink/pulse timing) and `render_mascot(visual_state, tick_count, width, height) -> list[Cell]`. Used by both `mascot.py` and `unified.py`.
- `clippy/unified.py` — `UnifiedEffect` wraps an inner effect class + mascot overlay in a single state machine: `WATCHING → IMMINENT_EARLY → IMMINENT_DEEP → ACTIVE → CACKLING → loop`. Has its own `CursorShakeDetector` (only accepted during WATCHING and ACTIVE phases).
- `clippy/unified_runner.py` — Tattoy plugin entry point. Reads `CLIPPY_EFFECTS` env var (comma-separated), wraps effect class(es) in `UnifiedEffect`, runs protocol loop.
- `clippy/effects/` — Individual effect plugins. Each has `EFFECT_META` dict (required keys: `name`, `description`; optional: `overlay` for non-destructive overlays like mascot), a class-level `destructive` attribute (default `True`; set `False` for effects that don't overwrite terminal content), `cancel()` method, `is_done` property, and `if __name__ == "__main__": run(Effect())`.
- `clippy/effects/mascot.py` — Standalone mascot overlay (used only for `--demo mascot`; has its own `CursorShakeDetector`). In tattoy mode, mascot rendering is handled by `UnifiedEffect`.
- `clippy/noise.py` — Pure Python 3D simplex noise (`noise3(x, y, z) -> float in [-1.0, 1.0]`). Used by fire for flow fields. No dependencies.
- `clippy/themes.py` — Theme system: `Theme` dataclass (18 named RGB colors in standard terminal color scheme format), `DemoTheme` dataclass (ANSI escape strings for demo-mode IDE rendering), color scheme JSON parsing (`parse_theme_json()`), palette TOML generation (`theme_to_palette_toml()`), demo theme derivation (`theme_to_demo_theme()`), persistence (`get_active_theme()` / `set_active_theme_name()` via `~/.cache/clippys-revenge/theme.json`), bundled theme loading, user theme import (file or URL via `urllib.request`). `default_demo_theme()` returns the original hardcoded VS Code dark+ colors for backward compatibility.
- `clippy/theme_browser.py` — Interactive TUI theme browser using alternate screen buffer and raw terminal input (`tty`/`termios`). Arrow keys navigate, `/` enters search mode (substring filter), Enter selects and applies, `q`/Escape quits. Falls back to simple numbered list when raw terminal is unavailable (piped stdin, dumb terminal). **Important:** All TUI output uses `\r\n` (not bare `\n`) because raw terminal mode disables the kernel's LF→CRLF translation.
- `clippy/themes_data.json` — 35 curated themes in standard terminal color scheme JSON format (Tokyo Night, Dracula, Catppuccin x4, Nord, Gruvbox x2, Solarized x2, One Dark/Light, Monokai, Rose Pine x3, Kanagawa, Material, Ayu x2, Everforest x2, GitHub x2, Tomorrow Night, Nightfox, Palenight, Tokyonight Storm, Zenburn, Synthwave 84, Horizon Dark, Cobalt2, Poimandres, Snazzy).
- `clippy/launcher.py` — CLI entry point. Discovers effects, generates tattoy config, execs tattoy. Uses `unified_runner.py` as the single plugin entry point (no separate mascot plugin). Supports `--version`/`-V`, `--shake off|N`, `--startup-pause`, `--theme NAME`, `--themes`, `--theme-list`, `--theme-import PATH`, `--theme-reset` flags. Configures ALT+T as tattoy keybinding to toggle effects on/off. Shell fallback chain: `$SHELL → shutil.which("bash") → /bin/sh`.
- `clippy/demo.py` — ANSI terminal renderer for `--demo` mode (no tattoy required). Accepts an optional `DemoTheme` parameter; defaults to `default_demo_theme()` when no theme is active.
- `clippy/ide_template.py` — Generates a fake VS Code-style Python editor background for `--demo` mode. Effects render on top, visually destroying the code.
- `bin/clippy` — Shell wrapper that sets `PYTHONPATH` and execs `python3 -m clippy.launcher`.
- `install.sh` / `uninstall.sh` — Install to `~/.local/share/clippys-revenge`, symlink `bin/clippy` to `~/.local/bin/clippy`.
- `native/` — Optional Rust (PyO3) extension module `clippy_native`. Contains `Cargo.toml`, `pyproject.toml` (maturin), and `src/lib.rs`. Provides `serialize_cells`, `serialize_pixels`, `tint_color`, `fade_color`, `noise3`, `compute_heat`, and `native_version`. Build with `cd native && maturin develop --release`. All functions have pure-Python fallbacks; the native module is never required. Use `CLIPPY_FORCE_PYTHON=1` to disable native dispatch. To add a new Rust function: implement in `lib.rs`, register in the `clippy_native` pymodule, add try-import at the call site with Python fallback.

**Effect protocol:** Defined formally in `harness.py` as a `typing.Protocol`. Every effect class implements: `on_pty_update(PTYUpdate)`, `on_resize(TTYResize)`, `tick() -> list[OutputMessage]`, `cancel()`, and `is_done` property.

**Testing seam:** `step(effect, messages) -> list[str]` is the primary test surface for effects — it parses messages, dispatches callbacks, calls tick, and returns serialized JSON. No threading involved. Use this instead of `run()` for effect unit tests.

## Wire Format (Critical)

`output_cells` and `output_pixels` use **direct arrays**, NOT nested objects:

```json
{"output_cells": [{"character": "X", "coordinates": [5, 3], "fg": [1.0, 0.0, 0.0, 1.0], "bg": null}]}
{"output_pixels": [{"coordinates": [79, 47], "color": [0.0, 1.0, 0.0, 1.0]}]}
```

`output_text` uses a nested struct:

```json
{"output_text": {"text": "hello", "coordinates": [10, 5], "fg": [0.0, 1.0, 0.0, 1.0], "bg": null}}
```

The golden files in `tests/golden/` are the source of truth for wire format.

**Pixel coordinate space:** Pixel y-range is `[0, height*2)` not `[0, height)`. Each cell row contains two pixel rows (upper half `▀`, lower half `▄`). For an 80x24 terminal, max valid pixel coordinate is `(79, 47)`.

## Conventions

- `slots=True` on all dataclasses
- All non-determinism injected via constructor (`seed` param → `random.Random(seed)`)
- `run()` seams: `clock`, `writer`, `flush`, `reader` — all injectable for testing
- Interruptible sleep via `shutdown.wait(timeout=...)`, never `time.sleep()`
- Logging to `~/.cache/clippys-revenge/logs/clippy-<name>.log` — NEVER write logs to stdout (corrupts protocol)
- `CLIPPY_FPS` env var overrides frame rate; `CLIPPY_LOG_LEVEL` controls log verbosity
- `CLIPPY_EFFECTS` env var (comma-separated) tells `unified_runner.py` which effect(s) to load
- `CLIPPY_INTERVAL` env var overrides idle time between effect cycles (default `300` = 5 min)
- `CLIPPY_FORCE_PYTHON` env var (`1`/`true`/`yes`) disables native module dispatch
- `CLIPPY_NO_TOAST` env var (`1`/`true`/`yes`) suppresses the startup mode toast
- `CLIPPY_SHAKE` env var — `off` to disable cursor-shake detection, or a positive integer to set reversal threshold (default `5`)
- Launcher auto-detects Rust toolchain and builds `clippy_native` on first run if `cargo` is available
- Active theme persisted in `~/.cache/clippys-revenge/theme.json`; user-imported themes stored in `~/.cache/clippys-revenge/themes/*.json`
- Theme palette written to `~/.cache/clippys-revenge/palette.toml` (258 entries: ANSI 0-15 from theme, 16-231 standard xterm 6x6x6 cube, 232-255 standard grayscale, plus foreground/background)
- `default_palette.toml` is generated from `default_theme()` — to update it, run `theme_to_palette_toml(default_theme())` and write the output

## Testing Patterns

- **Golden files** in `tests/golden/` validate wire format against hardcoded JSON. This is the only protection against consistently-wrong serialization.
- **Property-based tests** for effects: assert coordinates in bounds, colors in `[0.0, 1.0]`, correct output types — parametrized over multiple seeds.
- **`MessageReader`** helper in `test_harness.py` prevents premature shutdown in `run()` tests (plain `io.StringIO` hits EOF instantly, setting the shutdown event).
- **Malformed input resilience:** `from_json()` returns `None` for empty lines, whitespace, invalid JSON, unknown keys, null payloads — harness must never crash on bad input.
- **Unified lifecycle** (`UnifiedEffect`): `WATCHING → IMMINENT_EARLY → IMMINENT_DEEP → ACTIVE (inner effect) → CACKLING → loop` (live) or `→ DONE` (demo). Cursor-shake: WATCHING → jump to IMMINENT_DEEP; ACTIVE → cancel inner effect; all other phases ignore L+R completely.
- Inner effect lifecycles (standalone, driven by `cancel()` / `is_done`):
  - Fire: `IDLE → SPREADING → BURNING → WASTELAND → DONE` (or `cancel()` → `CANCEL_FADING → DONE`)
  - Invaders: `IDLE → BOMBARDMENT → ACTIVE → FADING → DONE` (ACTIVE capped at 1050 ticks; `cancel()` skips to FADING)
  - Grove: `IDLE → GROWING → PERCHING → FADING → DONE` (`cancel()` skips to FADING)
  - Microbes: `IDLE → SWARMING → FADING → DONE` (`cancel()` skips to FADING)
  - Paperclips: `IDLE → SEEDING → REPLICATING → FILLING → EARTH_TRANSITION → EARTH_REPLICATING → FADING → DONE` (`cancel()` skips to FADING)
  - Mascot: standalone only (`--demo mascot`): `WATCHING → IMMINENT_EARLY → IMMINENT_DEEP → CACKLING → DONE` (demo) or loop (live). Has own `CursorShakeDetector`.
- **Theme round-trip test:** `default_theme()` → `theme_to_palette_toml()` must match `default_palette.toml` byte-for-byte.
- **Demo backward compatibility:** All existing `test_demo.py` tests pass without a theme parameter — `demo_run()` defaults to `default_demo_theme()`.
- **TUI browser tests:** Mock `tty.setraw`, `termios.tcgetattr`/`tcsetattr`, `sys.stdin.read`, and `os.get_terminal_size` to test the full TUI interaction loop including key navigation, search filtering, and theme selection. Verify all output uses `\r\n` (not bare `\n`) for raw mode correctness.

## Mocking Quick Reference

| What | How | Why |
|---|---|---|
| `sys.stdin` | `io.StringIO` via fixture | Feed JSON lines to harness |
| `sys.stdout` | `writer=list.append` injection | Capture protocol output |
| `os.execvp` | `execvp=mock` injection | Prevent process replacement |
| `shutil.which` | `monkeypatch.setattr` | Test tattoy found/not-found |
| `os.get_terminal_size` | `monkeypatch.setattr` | Demo mode in headless CI |
| `time.monotonic` | `clock=fake_clock.now` injection | Deterministic tick timing |
| `random.Random` | `rng=Random(42)` injection | Reproducible effect output |
| `os.environ` | `monkeypatch.setenv` | Control `PATH`, `SHELL` |
| `clippy.themes._cache_dir` | `mock.patch` return `tmp_path` | Isolate theme persistence |
| `clippy.themes._themes_dir` | `mock.patch` return `tmp_path` | Isolate user theme storage |
| `tty.setraw` / `termios.*` | `mock.patch` | Test TUI browser without real terminal |

