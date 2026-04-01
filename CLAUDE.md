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
- `clippy/effects/` — Individual effect plugins. Each has `EFFECT_META` dict, `cancel()` method, `is_done` property, and `if __name__ == "__main__": run(Effect())`.
- `clippy/effects/mascot.py` — Standalone mascot overlay (used only for `--demo mascot`; has its own `CursorShakeDetector`). In tattoy mode, mascot rendering is handled by `UnifiedEffect`.
- `clippy/noise.py` — Pure Python 3D simplex noise (`noise3(x, y, z) -> float in [-1.0, 1.0]`). Used by fire for flow fields. No dependencies.
- `clippy/launcher.py` — CLI entry point. Discovers effects, generates tattoy config, execs tattoy. Uses `unified_runner.py` as the single plugin entry point (no separate mascot plugin).
- `clippy/demo.py` — ANSI terminal renderer for `--demo` mode (no tattoy required).
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

