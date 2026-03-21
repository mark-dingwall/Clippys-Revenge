#!/bin/bash
# Clippy's Revenge — installer
#
# Usage:
#   bash install.sh           # install latest from GitHub
#   bash install.sh --from-local   # install from this working directory (for development)
#   curl -fsSL https://raw.githubusercontent.com/Axionatic/Clippys-Revenge/main/install.sh | bash

set -euo pipefail

INSTALL_DIR="$HOME/.local/share/clippys-revenge"
BIN_DIR="$HOME/.local/bin"
REPO_URL="https://github.com/Axionatic/Clippys-Revenge.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

# -- Argument parsing --------------------------------------------------------

LOCAL=false
for arg in "$@"; do
    case "$arg" in
        --from-local) LOCAL=true ;;
        *) printf '\033[1;31m::\033[0m Unknown argument: %s\n' "$arg" >&2; exit 1 ;;
    esac
done

if [ "$LOCAL" = true ] && [ -z "$SCRIPT_DIR" ]; then
    printf '\033[1;31m::\033[0m --from-local requires the script to be run from a file, not piped.\n' >&2
    exit 1
fi

# -- Helpers ----------------------------------------------------------------

info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m::\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m::\033[0m %s\n' "$*"; }
err()   { printf '\033[1;31m::\033[0m %s\n' "$*" >&2; }

# -- Root check -------------------------------------------------------------

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    warn "Running as root — files will be installed into root's \$HOME."
    warn "This is usually not what you want."
    answer=""
    printf '    Continue anyway? [y/N] '
    { read -r answer </dev/tty; } 2>/dev/null || true
    case "${answer:-n}" in
        [Yy]*) ;;
        *)
            err "Aborted."
            exit 1
            ;;
    esac
fi

# -- Previous-install ownership check ---------------------------------------

if [ -d "$INSTALL_DIR" ] && [ ! -w "$INSTALL_DIR" ]; then
    err "Cannot write to $INSTALL_DIR (owned by a different user)."
    err "This usually happens when a previous install was run with sudo."
    err ""
    err "To fix, uninstall first then re-run this installer:"
    err "  sudo bash $INSTALL_DIR/uninstall.sh"
    err "  bash install.sh"
    exit 1
fi

# -- Dependency checks ------------------------------------------------------

info "Checking dependencies..."

# Python 3.10+
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install Python 3.10+ and try again."
    exit 1
fi

py_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
py_major="${py_version%%.*}"
py_minor="${py_version##*.}"

if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
    err "Python 3.10+ required (found $py_version)."
    exit 1
fi
ok "Python $py_version"

# Git (not needed for --from-local installs)
if [ "$LOCAL" = false ]; then
    if ! command -v git &>/dev/null; then
        err "git not found. Install git and try again."
        exit 1
    fi
    ok "git $(git --version | awk '{print $3}')"
fi

# -- Tattoy detection -------------------------------------------------------

tattoy_bin=""
if command -v tattoy &>/dev/null; then
    tattoy_bin="$(command -v tattoy)"
elif [ -x "$HOME/.cargo/bin/tattoy" ]; then
    tattoy_bin="$HOME/.cargo/bin/tattoy"
fi

if [ -n "$tattoy_bin" ]; then
    ok "tattoy found at $tattoy_bin"
else
    warn "tattoy not found (needed at runtime, not for install)."
    if command -v cargo &>/dev/null; then
        answer="n"
        printf '    Install tattoy via cargo? [Y/n] '
        { read -r answer </dev/tty; } 2>/dev/null || true
        case "${answer:-y}" in
            [Yy]*)
                info "Running: cargo install tattoy"
                cargo install tattoy
                ok "tattoy installed"
                ;;
            *)
                info "Skipping tattoy install. You can install it later:"
                info "  cargo install tattoy"
                info "  or visit https://tattoy.sh"
                ;;
        esac
    else
        info "Install tattoy before running clippy:"
        info "  https://tattoy.sh"
    fi
fi

# -- Project installation ---------------------------------------------------

if [ "$LOCAL" = true ]; then
    info "Installing from local source: $SCRIPT_DIR"
    if [ -d "$INSTALL_DIR" ]; then
        if ! rm -rf "$INSTALL_DIR"; then
            err "Cannot remove $INSTALL_DIR (permission denied)."
            err "Try: sudo rm -rf $INSTALL_DIR"
            exit 1
        fi
    fi
    if ! cp -r "$SCRIPT_DIR" "$INSTALL_DIR"; then
        err "Failed to copy files to $INSTALL_DIR."
        exit 1
    fi
    # Remove .git so a later normal install sees a clean slate and re-clones
    rm -rf "$INSTALL_DIR/.git"
    ok "Copied local files"
elif [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing install..."
    if ! git -C "$INSTALL_DIR" pull --ff-only; then
        err "git pull failed in $INSTALL_DIR."
        err "If this is a permissions issue, uninstall and re-install:"
        err "  sudo bash $INSTALL_DIR/uninstall.sh"
        err "  bash install.sh"
        exit 1
    fi
else
    if [ -d "$INSTALL_DIR" ]; then
        warn "Removing stale install dir (not a git repo)..."
        if ! rm -rf "$INSTALL_DIR"; then
            err "Cannot remove $INSTALL_DIR (permission denied)."
            err "Try: sudo rm -rf $INSTALL_DIR"
            exit 1
        fi
    fi
    info "Cloning Clippy's Revenge..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# -- Mark executables -------------------------------------------------------

if ! chmod +x "$INSTALL_DIR/bin/clippy"; then
    err "Cannot set executable permissions on $INSTALL_DIR/bin/clippy."
    err "If a previous install was run with sudo, uninstall first:"
    err "  sudo bash $INSTALL_DIR/uninstall.sh"
    err "  bash install.sh"
    exit 1
fi
for f in "$INSTALL_DIR"/clippy/effects/*.py; do
    [ -f "$f" ] && chmod +x "$f"
done

# -- Symlink ----------------------------------------------------------------

mkdir -p "$BIN_DIR"
if ! ln -sf "$INSTALL_DIR/bin/clippy" "$BIN_DIR/clippy"; then
    err "Cannot create symlink at $BIN_DIR/clippy (permission denied)."
    err "Check permissions on $BIN_DIR."
    exit 1
fi
ok "Symlinked $BIN_DIR/clippy"

# -- PATH check -------------------------------------------------------------

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR is not on your PATH."
        info "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
        info "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

# -- Done -------------------------------------------------------------------

echo ""
ok "Clippy's Revenge installed!"
echo ""
info "Usage:"
info "  clippy              # launch with a random effect"
info "  clippy --list       # list available effects"
info "  clippy --effect fire"
info "  clippy -- vim       # wrap a specific command"
echo ""
info "Uninstall:  bash $INSTALL_DIR/uninstall.sh"
