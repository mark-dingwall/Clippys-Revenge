# Changelog

## 1.0.0

Initial release.

### Effects

- **Fire** — terminal conflagration with heat simulation, ember system, and simplex noise smoke
- **Invaders** — bombardment phase followed by full alien invasion with procedural sprites
- **Grove** — nature reclaims the terminal: grass, flowers, trees, birds, butterflies
- **Microbes** — colorful organisms dash along curved Catmull-Rom spline paths
- **Paperclips** — exponential paperclip replication consumes the screen, then the world
- **Mascot** — Clippy watches from the corner (demo-only standalone overlay)

### Theme System

- 35 bundled color themes (Tokyo Night, Dracula, Catppuccin, Nord, Gruvbox, Solarized, One Dark, Monokai, Rose Pine, and more)
- Interactive TUI theme browser with search filtering (`--themes`)
- Apply themes by name (`--theme dracula`), persisted across runs
- Import custom color scheme JSON files or URLs (`--theme-import`)
- Palette generation for tattoy (ANSI 0-15 from theme, 16-231 xterm cube, 232-255 grayscale)
- Default theme: Tokyo Night

### CLI

- `--version` / `-V` — show version
- `--effects` / `-e` — comma-separated effect name(s) (default: cycle all)
- `--list` / `-l` — list available effects
- `--demo NAME` — standalone ANSI preview, no tattoy required
- `--themes` — interactive theme browser
- `--theme NAME` — apply a named theme
- `--theme-import PATH` — import color scheme JSON (file or URL)
- `--theme-list` — list theme names (non-interactive)
- `--theme-reset` — reset to default theme
- `--optimised on|off` — force Rust acceleration on or off (default: auto-detect)
- `--shake off|N` — disable or tune cursor-shake sensitivity
- `--startup-pause` — pause after startup diagnostics and wait for Enter before launching
- ALT+T keybinding to toggle effects on/off while running

### Features

- Unified effect lifecycle with mascot overlay (WATCHING → IMMINENT → ACTIVE → CACKLING)
- Cursor shake detection (5 L+R reversals within 2s) for skipping idle or cancelling effects
- Effect cycling with anti-repeat shuffle in live mode
- Demo mode with VS Code-style IDE background template
- tattoy plugin protocol: line-delimited JSON on stdin/stdout

### Optional Rust Acceleration

- PyO3 extension module (`clippy_native`) via maturin
- 7 accelerated functions: `serialize_cells`, `serialize_pixels`, `tint_color`, `fade_color`, `noise3`, `compute_heat`, `native_version`
- Auto-build on first run when `cargo` is available
- Pure-Python fallback for every native function — Rust is never required
- `CLIPPY_FORCE_PYTHON=1` env var to disable native dispatch
- `--optimised on|off` flag for explicit control

### Performance

- Hand-rolled JSON serialization (no `json.dumps` overhead in hot path)
- Centralized compositor in `UnifiedEffect` — single `output_cells` message per frame

### Infrastructure

- Zero third-party dependencies (stdlib only, Python 3.10+)
- Golden file testing for wire format correctness
- Property-based testing for coordinate bounds and color ranges
- 703 tests across 19 test files
- File logging to `~/.cache/clippys-revenge/logs/` (never stdout — protects protocol)
- Shell fallback chain: `$SHELL` → `bash` → `/bin/sh`
- Environment variables: `CLIPPY_FPS`, `CLIPPY_LOG_LEVEL`, `CLIPPY_EFFECTS`, `CLIPPY_INTERVAL`, `CLIPPY_FORCE_PYTHON`, `CLIPPY_NO_TOAST`, `CLIPPY_SHAKE`
- install.sh / uninstall.sh (`~/.local/share/clippys-revenge`, symlink to `~/.local/bin/clippy`)
- PEP 561 py.typed marker
