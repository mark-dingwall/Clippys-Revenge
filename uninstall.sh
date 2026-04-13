#!/bin/bash
# Clippy's Revenge — uninstaller

set -euo pipefail

INSTALL_DIR="$HOME/.local/share/clippys-revenge"
BIN_LINK="$HOME/.local/bin/clippy"
TMP_DIR="${TMPDIR:-/tmp}/clippys-revenge"
CACHE_DIR="$HOME/.cache/clippys-revenge"

info() { printf '\033[1;34m::\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m::\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m::\033[0m %s\n' "$*" >&2; }

failed=0

info "Uninstalling Clippy's Revenge..."

# -- Remove symlink ---------------------------------------------------------

if [ -L "$BIN_LINK" ] || [ -f "$BIN_LINK" ]; then
    if rm -f "$BIN_LINK"; then
        ok "Removed $BIN_LINK"
    else
        err "Cannot remove $BIN_LINK (permission denied)."
        failed=1
    fi
fi

# -- Remove install directory -----------------------------------------------

if [ -d "$INSTALL_DIR" ]; then
    if rm -rf "$INSTALL_DIR"; then
        ok "Removed $INSTALL_DIR"
    else
        err "Cannot remove $INSTALL_DIR (permission denied)."
        failed=1
    fi
fi

# -- Remove temp directory --------------------------------------------------

if [ -d "$TMP_DIR" ]; then
    if rm -rf "$TMP_DIR"; then
        ok "Removed $TMP_DIR"
    else
        err "Cannot remove $TMP_DIR (permission denied)."
        failed=1
    fi
fi

# -- Remove cache directory ----------------------------------------------------

if [ -d "$CACHE_DIR" ]; then
    if rm -rf "$CACHE_DIR"; then
        ok "Removed $CACHE_DIR"
    else
        err "Cannot remove $CACHE_DIR (permission denied)."
        failed=1
    fi
fi

# -- Result -----------------------------------------------------------------

echo ""
if [ "$failed" -ne 0 ]; then
    if [ "${EUID:-$(id -u)}" -ne 0 ]; then
        err "Some files could not be removed due to permissions."
        err "Re-run with sudo:  sudo bash uninstall.sh"
    else
        err "Some files could not be removed even as root."
        err "Check the paths above and remove them manually."
    fi
    exit 1
fi

ok "Clippy's Revenge uninstalled."
info "Note: tattoy was not removed. Uninstall it separately if desired."
