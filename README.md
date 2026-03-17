# Clippy's Revenge

> "It looks like you're trying to use a terminal. Would you like me to set it on fire?"

Clippy's Revenge is a visual effects plugin system for [tattoy](https://tattoy.sh), the Rust terminal compositor. Your terminal. On fire. With space invaders. You asked for this.

## What is this?

A collection of animated effects that overlay your terminal using tattoy's plugin protocol. Each effect is a small Python process that reads JSON from stdin and writes JSON to stdout — stdlib only, no dependencies.

## Requirements

- [tattoy](https://tattoy.sh) installed and on your `PATH`
- Python 3.10+

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/tombh/clippys-revenge/main/install.sh | bash
```

Or manually:

```bash
git clone https://github.com/tombh/clippys-revenge
cd clippys-revenge
./install.sh
```

This installs to `~/.local/share/clippys-revenge` and symlinks `clippy` into `~/.local/bin/`.

## Usage

```bash
# Launch with a random effect
clippy

# Pick a specific effect
clippy --effect fire

# See what's available
clippy --list

# Try an effect without tattoy (demo mode)
clippy --demo fire

# Custom frame rate
clippy --fps 60
```

## Effects

**fire** — Your terminal, but worse. Text you type slowly ignites and burns to ash. The cursor is the source. Shake it to extinguish the flames, if you dare.

**invaders** — Space invaders rain pixel-art chaos onto your code. Watch them glide across the top of your terminal before the inevitable bombing run.

**grove** — A vibrant grove grows from the terminal bottom, birds perch in the branches, then everything gently fades.

**microbes** — Colorful microbes dash along curved paths across your screen before fading out.

**mascot** — Clippy watches from the corner with gleeful menace. The longer you idle, the more excited he gets.

## Hacking / Writing Your Own Effect

See [CLAUDE.md](CLAUDE.md) for architecture details, wire format, and testing patterns. Effects live in `clippy/effects/` — each is a standalone Python module with an `EFFECT_META` dict and a class implementing `on_pty_update`, `on_resize`, and `tick`.

```bash
# Run the test suite
python3 -m pytest tests/ -v
```

## Uninstall

```bash
~/.local/share/clippys-revenge/uninstall.sh
```

## License

MIT
