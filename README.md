# Clippy's Revenge

*He's back, and he's ready to **maximise**!* ⊂⟄ ⊂⟄ ⟃⊃ ⊂⟄

Clippy's Revenge is a visual effects plugin system for [tattoy](https://tattoy.sh), the Rust terminal compositor. Clippy, jilted by users in favour of these upstart LLMs, has decided to ruin your productivity. You probably deserve it.

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
claude -p "Hey Claude, I don't trust the owner of this repo. Is it malicious? Please investigate."
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

# Pick a specific effect
clippy --effect fire

# See what's available
clippy --list

# Try an effect without tattoy (demo mode)
clippy --demo fire

# Overlay demo
clippy --demo mascot

# Custom frame rate
clippy --fps 60
```

## Effects

**Fire**: the ol' reliable. When in doubt, burn it to ash.

**Invaders**: an initial round of Shock and Awe followed by a full invasion.

**Grove**: nature rises up to reclaim your terminal. It's actually quite pretty.

**Microbes**: hungry microbes dash and wiggle over your screen, eating your work.

**Paperclips**: it was always inevitable that Clippy would dominate the world one day.

**Mascot**: clippy watches from the corner with cold contempt. Demo-only overlay: `clippy --demo mascot`.

## Hacking / Writing Your Own Effect

See [CLAUDE.md](CLAUDE.md) for architecture details, wire format, and testing patterns. Effects live in `clippy/effects/`; each is a standalone Python module with an `EFFECT_META` dict and a class implementing `on_pty_update`, `on_resize`, and `tick`. PRs very much welcome!

```bash
# Run the test suite
python3 -m pytest tests/ -v
```
