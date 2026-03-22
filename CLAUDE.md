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
python3 -m clippy.launcher --effect fire

# Custom frame rate
python3 -m clippy.launcher --fps 60

# List effects
python3 -m clippy.launcher --list
```

Note: Use `python3`, not `python`, on this system.

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
- `clippy/unified_runner.py` — Tattoy plugin entry point. Reads `CLIPPY_EFFECT` env var, wraps effect class in `UnifiedEffect`, runs protocol loop.
- `clippy/effects/` — Individual effect plugins. Each has `EFFECT_META` dict, `cancel()` method, `is_done` property, and `if __name__ == "__main__": run(Effect())`.
- `clippy/effects/mascot.py` — Standalone mascot overlay (used only for `--demo mascot`; has its own `CursorShakeDetector`). In tattoy mode, mascot rendering is handled by `UnifiedEffect`.
- `clippy/noise.py` — Pure Python 3D simplex noise (`noise3(x, y, z) -> float in [-1.0, 1.0]`). Used by fire and grove for flow fields. No dependencies.
- `clippy/launcher.py` — CLI entry point. Discovers effects, generates tattoy config, execs tattoy. Uses `unified_runner.py` as the single plugin entry point (no separate mascot plugin).
- `clippy/demo.py` — ANSI terminal renderer for `--demo` mode (no tattoy required).
- `clippy/ide_template.py` — Generates a fake VS Code-style Python editor background for `--demo` mode. Effects render on top, visually destroying the code.
- `bin/clippy` — Shell wrapper that sets `PYTHONPATH` and execs `python3 -m clippy.launcher`.
- `install.sh` / `uninstall.sh` — Install to `~/.local/share/clippys-revenge`, symlink `bin/clippy` to `~/.local/bin/clippy`.

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

---

## Code Review Sections (temporary — delete after review)

### Section 1: Wire Protocol & Types

**Files:** `clippy/types.py`, `tests/golden/` (9 golden JSON files), `tests/test_types.py`

**What to look for:**
- `from_json()` round-trip correctness for all message types (PTYUpdate, TTYResize)
- CursorShakeDetector constants: WINDOW_TICKS=60, REVERSALS_NEEDED=5 — does this match the documented "2s @30fps"? (60 ticks / 30fps = 2s, yes)
- `_validated_tuple()` edge cases — does it handle non-list inputs, wrong-length tuples, non-numeric elements?
- Golden files in `tests/golden/` — do they match the actual wire format tattoy expects? Are there message types missing golden coverage?
- Color type alias `tuple[float, float, float, float]` — sufficient or should it be a NamedTuple for clarity?
- `to_json()` on OutputCells/OutputPixels — confirm direct array format (NOT nested `"cells"` / `"pixels"` key)

### Section 2: Harness & Runtime

**Files:** `clippy/harness.py`, `clippy/unified.py`, `clippy/unified_runner.py`, `tests/test_harness.py`, `tests/test_unified.py`

**What to look for:**
- `Effect` Protocol (harness.py:28-31) is incomplete — missing `cancel()` and `is_done` (will be fixed in Step 2)
- Clear-frame logic: after effect returns OutputCells, a one-shot empty OutputCells is sent when tick() returns []. Does this work correctly for effects that alternate between OutputCells and OutputPixels?
- Shutdown event / listener thread cleanup — any race conditions? The daemon thread reads stdin; main thread checks shutdown event. Is there a window where messages could be lost?
- `unified_runner.py` error handling — what happens if CLIPPY_EFFECT names a nonexistent effect? (Answer: ValueError raised, unhandled — should this be caught?)
- UnifiedEffect `_advance_queue` anti-repeat logic — does it work correctly with a 1-element effect list?
- Frame budget calculation in `run()` — confirm sleep time is correctly computed as `max(0, budget - elapsed)`

### Section 3: Effect Implementations

**Files:** `clippy/effects/fire.py`, `invaders.py`, `grove.py`, `microbes.py`, `paperclips.py`, `mascot.py` — each with its corresponding `tests/test_*.py`

**What to look for:**
- `cancel()` / `is_done` consistency: mascot.py is missing both (will be fixed in Step 2). All other effects have them.
- Phase transition exhaustiveness — can any effect get stuck in a phase forever? Check timeout/tick-count caps.
- Mascot rendering duplication: `mascot.py` lines 12-82 + 170-232 are nearly identical to `unified.py` lines 25-63 + 257-321 (will be fixed in Step 3)
- EFFECT_META consistency — do all effects have `name` and `description`? Only mascot has `overlay: True`.
- `idle_secs=0` (demo mode) path — does every effect handle this correctly? (IDLE phase should be skipped)
- Bounds checking: are all emitted coordinates guaranteed within `[0, width) x [0, height)`? Pixel effects: `[0, width) x [0, height*2)`?

### Section 4: Launcher & CLI

**Files:** `clippy/launcher.py`, `tests/test_launcher.py`

**What to look for:**
- TOML escaping in `generate_config()` — are paths with quotes, backslashes, or Unicode handled? (Test exists for backslash escaping)
- PYTHONPATH manipulation — could the project root be added twice if already present?
- Overlay filtering: `--list` and `--effect` exclude overlays, `--demo` allows them. Is this consistently enforced?
- `find_tattoy()` fallback to `~/.cargo/bin/tattoy` — should this also check `/usr/local/bin`?
- `ensure_executable()` — adds shebang + chmod. Is this idempotent? (Test says yes)
- Error messages for missing tattoy, unknown effects, no effects discovered — are they helpful?
- `--fps` validation — what happens with `--fps 0` or `--fps -1`?

### Section 5: Demo & Rendering

**Files:** `clippy/demo.py`, `clippy/ide_template.py`, `tests/test_demo.py`

**What to look for:**
- `demo_run()` phase-done check at line ~239: `getattr(effect, "phase", None)` — does this work for both UnifiedEffect (has `.phase` via `_phase`) and standalone effects? (UnifiedEffect exposes `phase` property? Check.)
- `_highlight_python()` regex in ide_template.py — any edge cases with multiline strings or escaped quotes?
- `build_template()` output dimensions — is it guaranteed to return exactly `height` rows of exactly `width` chars?
- **Stale file tree** in ide_template.py `_TREE` (lines 21-45) — missing: grove.py, microbes.py, paperclips.py, mascot.py, unified.py, unified_runner.py, noise.py, and test files for grove/microbes/paperclips/mascot/unified/noise (will be fixed in Step 4c)
- Half-block pixel rendering — does the upper/lower mapping (▀ for even y, ▄ for odd y) handle the boundary correctly at y=height*2-1?

### Section 6: Packaging & Install

**Files:** `pyproject.toml`, `install.sh`, `uninstall.sh`, `bin/clippy`

**What to look for:**
- `pyproject.toml` already declares version `1.0.0` — is this premature or intentional?
- `bin/clippy` uses `readlink -f` — this doesn't exist on stock macOS (needs `greadlink` or a different approach). Is this a supported platform?
- `install.sh` — does `--from-local` vs default (git clone) work correctly? Permission handling?
- `uninstall.sh` does NOT clean `~/.cache/clippys-revenge/` (logs, config) — is this intentional? Should it offer to clean cache?
- `py.typed` marker is missing — PEP 561 compliance (will be added in Step 4d)
- Are there any files that should be in `.gitignore` but aren't?
