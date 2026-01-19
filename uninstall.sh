#!/usr/bin/env bash
#
# amenity-stuff uninstaller
# Usage: curl -sSL https://raw.githubusercontent.com/elmisi/amenity-stuff/main/uninstall.sh | sh
#
set -e

APP_NAME="amenity-stuff"
CONFIG_DIR="$HOME/.config/amenity-stuff"

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    BOLD=''
    NC=''
fi

info()    { printf "${BLUE}ℹ${NC} %s\n" "$1"; }
success() { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn()    { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
error()   { printf "${RED}✗${NC} %s\n" "$1"; }
header()  { printf "\n${BOLD}%s${NC}\n" "$1"; }

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

header "Uninstalling $APP_NAME"

# Try pipx first, then pip
if has_cmd pipx && pipx list 2>/dev/null | grep -q "$APP_NAME"; then
    info "Removing via pipx..."
    pipx uninstall "$APP_NAME" && success "Removed $APP_NAME via pipx" || warn "pipx uninstall failed"
elif has_cmd pip3 && pip3 show "$APP_NAME" >/dev/null 2>&1; then
    info "Removing via pip3..."
    pip3 uninstall -y "$APP_NAME" && success "Removed $APP_NAME via pip3" || warn "pip3 uninstall failed"
elif has_cmd pip && pip show "$APP_NAME" >/dev/null 2>&1; then
    info "Removing via pip..."
    pip uninstall -y "$APP_NAME" && success "Removed $APP_NAME via pip" || warn "pip uninstall failed"
else
    warn "$APP_NAME not found (pipx/pip)"
fi

# Config directory
if [ -d "$CONFIG_DIR" ]; then
    printf "\n"
    printf "Remove configuration directory?\n"
    printf "  ${YELLOW}%s${NC}\n" "$CONFIG_DIR"
    printf "  (contains settings, taxonomy, etc.)\n"
    printf "Remove? [y/N] "
    read -r answer
    case "$answer" in
        [Yy]*)
            rm -rf "$CONFIG_DIR"
            success "Removed $CONFIG_DIR"
            ;;
        *)
            info "Kept $CONFIG_DIR"
            ;;
    esac
fi

printf "\n"
info "Note: Cache directories (.amenity-stuff/) in source folders are not removed."
info "      Remove them manually if needed."

printf "\n"
success "Uninstall complete"
