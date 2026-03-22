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

# Pick a specific effect
clippy --effect fire

# See what's available
clippy --list

# Try an effect without tattoy
clippy --demo fire

# The many faces of Clippy
clippy --demo mascot
```

## Effects

**Fire**: the ol' reliable. When in doubt, burn it to ash.

**Invaders**: an initial round of Shock and Awe followed by full invasion.

**Grove**: nature rises up to reclaim your terminal. It's actually quite pretty.

**Microbes**: hungry microbes dash and wiggle over your screen, eating your work.

**Paperclips**: it was inevitable that Clippy would dominate the world one day.

**Mascot**: Clippy watches from the corner with poorly-concealed contempt. Running effects that break flow and ruin your productivity is the only thing that brings joy to his cold, calloused heart.

## Hacking / Writing Your Own Effect

See [CLAUDE.md](CLAUDE.md) for architecture details, wire format, and testing patterns. Effects live in `clippy/effects/`; each is a standalone Python module with an `EFFECT_META` dict and a class implementing the `Effect` protocol: `on_pty_update`, `on_resize`, `tick`, `cancel`, and `is_done`. PRs very much welcome!

```bash
# Install dev dependencies
python3 -m pip install -e ".[dev]"

# Run the test suite
python3 -m pytest tests/ -v
```
