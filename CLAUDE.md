# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Clippy's Revenge is a Python plugin system for [tattoy](https://tattoy.sh) (a Rust terminal compositor). Plugins communicate with tattoy via line-delimited JSON on stdin/stdout. The project has zero third-party Python dependencies — stdlib only, Python 3.10+. `pytest` is the sole dev dependency.

## Commands

```bash
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

- `clippy/types.py` — Protocol dataclasses (`Cell`, `Pixel`, `PTYUpdate`, `TTYResize`, `OutputText`, `OutputCells`, `OutputPixels`) and JSON serialization. `from_json()` never raises — returns `None` for any malformed input.
- `clippy/harness.py` — `Effect` protocol, `step()` (single-tick test seam), and `run()` (threaded stdin/stdout protocol loop with frame-rate control).
- `clippy/effects/` — Individual effect plugins. Each has `EFFECT_META` dict and `if __name__ == "__main__": run(Effect())`.
- `clippy/launcher.py` — CLI entry point. Discovers effects, generates tattoy config, execs tattoy.
- `clippy/demo.py` — ANSI terminal renderer for `--demo` mode (no tattoy required).
- `bin/clippy` — Shell wrapper that sets `PYTHONPATH` and execs `python3 -m clippy.launcher`.
- `install.sh` / `uninstall.sh` — Install to `~/.local/share/clippys-revenge`, symlink `bin/clippy` to `~/.local/bin/clippy`.

**Effect protocol:** Every effect class implements three methods: `on_pty_update(PTYUpdate)`, `on_resize(TTYResize)`, `tick() -> list[OutputMessage]`.

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
- Effect lifecycles:
  - Fire: `IDLE → SPREADING → BURNING → WASTELAND → FADING → DONE` (or `CANCEL_FADING → DONE` via cursor-shake)
  - Invaders: `IDLE → BOMBARDMENT → ACTIVE → FADING → DONE`

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
