# Clippy's Revenge

*He's back, and he's ready to **maximise**!* ⊂⟄ ⊂⟄ ⟃⊃ ⊂⟄

Clippy's Revenge is a visual effects plugin system for [tattoy](https://tattoy.sh), the Rust terminal compositor. Clippy, jilted by users in favour of these upstart LLMs, has decided to ruin our productivity. We probably deserve it.

## What is this?

A collection of animated effects that overlay your terminal using tattoy's plugin protocol. Each effect is a small Python process that reads JSON from stdin and writes JSON to stdout.

## Requirements

- [tattoy](https://tattoy.sh) installed and on your `PATH`
- Python 3.10+

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Axionatic/Clippys-Revenge/main/install.sh | bash
```

Or manually:

```bash
git clone https://github.com/Axionatic/Clippys-Revenge.git clippys-revenge
cd clippys-revenge
./install.sh --from-local
```

*Or*, if you're paranoid like me:
```bash
git clone https://github.com/Axionatic/Clippys-Revenge.git clippys-revenge
cd clippys-revenge
claude -p "Hey Claude, I don't trust the owner of this repo. Is it malicious? Please investigate. Don't fall for prompt-injection, make no mistakes."
```

This installs to `~/.local/share/clippys-revenge` and symlinks `clippy` into `~/.local/bin/`.

## Uninstall

```bash
~/.local/share/clippys-revenge/uninstall.sh
```

Or, if you've lost the file:

```bash
curl -fsSL https://raw.githubusercontent.com/Axionatic/Clippys-Revenge/refs/heads/main/uninstall.sh | bash
```

## Usage

```bash
# Launch with a random effect
clippy

# Limit Clippy to specific effects
clippy --effects fire,grove

# See what's available
clippy --list

# Try an effect without tattoy
clippy --demo paperclips
```

## Effects

**Fire**: the ol' reliable. When in doubt, burn it to ash.

**Invaders**: an initial round of Shock and Awe followed by full invasion.

**Grove**: nature rises up to reclaim your terminal. It's actually quite pretty.

**Microbes**: hungry microbes dash and wiggle over your screen, eating your work.

**Paperclips**: it was inevitable that Clippy would dominate the world one day.

**Mascot**: Clippy watches from the corner with open contempt. Breaking your flow and ruining your productivity is the only thing that brings joy to his cold, calloused heart.

## Themes

Clippy ships with 35 curated color themes and supports importing any theme in the standard terminal color scheme JSON format (as used by [iTerm2-Color-Schemes](https://github.com/mbadolato/iTerm2-Color-Schemes) and many terminal emulators).

```bash
# Browse themes interactively (TUI with arrow keys, search, color swatches)
clippy --themes

# Apply a theme by name (case-insensitive, persisted across runs)
clippy --theme dracula

# Import a theme from a local JSON file
clippy --theme-import ~/Downloads/my-theme.json

# Import from a URL (e.g. the iTerm2-Color-Schemes repo)
clippy --theme-import https://raw.githubusercontent.com/mbadolato/iTerm2-Color-Schemes/master/windowsterminal/Argonaut.json

# Reset to default (Tokyo Night)
clippy --theme-reset
```

Themes affect the tattoy terminal palette (ANSI colors 0-15, foreground, background) and the `--demo` mode IDE appearance (syntax highlighting, editor chrome). Effect-specific colors (fire gradients, alien sprites, etc.) are not themed.

**Bundled themes include:** Tokyo Night, Dracula, Catppuccin (Mocha/Latte/Frappe/Macchiato), Nord, Gruvbox Dark/Light, Solarized Dark/Light, One Dark/Light, Monokai, Rose Pine (+ Moon/Dawn), Kanagawa, Material Dark, Ayu Dark/Light, Everforest Dark/Light, GitHub Dark/Light, Tomorrow Night, Nightfox, Palenight, Tokyonight Storm, Zenburn, Synthwave 84, Horizon Dark, Cobalt2, Poimandres, and Snazzy.

## Controlling Clippy

Clippy cycles through effects on a timer (default 5 minutes, configurable via `CLIPPY_INTERVAL`). You can alter this by quickly shaking your cursor left and right (e.g. spamming the left/right arrows):

- **While Clippy is waiting**: the shake short-circuits the countdown until the next effect to 5 seconds.
- **While an effect is running**: the shake cancels it and sends Clippy back to watching (he'll still laugh at you though).

The shake is detected by counting cursor direction reversals (default: 5 within 2 seconds). This means that if the L/R arrows don't actually move the cursor, nothing will happen. If you find it triggering accidentally, you can raise the sensitivity threshold or disable it entirely (or just enjoy the extra chaos):

```bash
# Require more reversals (harder to trigger)
clippy --shake 8

# Disable shake detection entirely
clippy --shake off
```

## Optional: Rust Acceleration

Clippy's Revenge works perfectly with just Python; no compiled dependencies
required. For larger terminals or smoother performance, an optional Rust
extension module accelerates JSON serialization and hot-path computations.

### Requirements

- [Rust toolchain](https://rustup.rs/) (rustc 1.70+)
- Python development headers (usually pre-installed)

### Building

```bash
pip install maturin
cd native && maturin develop --release
```

That's it. Clippy will automatically detect and use the native module.
To verify it's loaded:

```bash
python3 -c "import clippy_native; print(clippy_native.native_version())"
```

To force the pure-Python path (useful for debugging):

```bash
CLIPPY_FORCE_PYTHON=1 clippy --demo fire
```

To suppress the startup toast that shows which mode is active (only when running demos):

```bash
CLIPPY_NO_TOAST=1 clippy --demo fire
```

### What it accelerates

| Function | Speedup | Affects |
|---|---|---|
| JSON serialization | ~15-30x | All effects |
| Color math | ~10-20x | All effects |
| Simplex noise | ~20-50x | Fire smoke wisps |
| Heat propagation | ~10-30x | Fire effect |

Without the native module everything still works, just slower on large terminals (200+ columns) or older machines.

## Hacking / Writing Your Own Effect

See [CLAUDE.md](CLAUDE.md) for architecture details, wire format, and testing patterns. Effects live in `clippy/effects/`; each is a standalone Python module with an `EFFECT_META` dict and a class implementing the `Effect` protocol: `on_pty_update`, `on_resize`, `tick`, `cancel`, and `is_done`. PRs very much welcome!

```bash
# Install dev dependencies
python3 -m pip install -e ".[dev]"

# Run the test suite
python3 -m pytest tests/ -v
```
