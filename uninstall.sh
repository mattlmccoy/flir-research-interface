#!/usr/bin/env bash
# FLIR Research Interface — uninstaller (macOS + Linux).
# Stops and removes the background service and the `fri-update` helper. Your recordings and camera
# credentials are left ALONE unless you pass --purge, which also deletes the checkout at $FRI_HOME.
# A recordings folder set via FRI_EXPERIMENTS_ROOT (e.g. a Dropbox folder) is never touched.
#   bash ~/flir-research-interface/uninstall.sh            # remove service + helper, keep code/data
#   bash ~/flir-research-interface/uninstall.sh --purge    # also remove the checkout
# Sourceable for tests with FRI_UNINSTALL_LIB=1 (defines functions without doing anything).
set -euo pipefail

DEST="${FRI_HOME:-$HOME/flir-research-interface}"
BIN_DIR="${FRI_BIN_DIR:-$HOME/.local/bin}"
LABEL="io.github.mattlmccoy.flir-research-interface"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

remove_service_macos() {
  local plist="$HOME/Library/LaunchAgents/$LABEL.plist"
  if [ -f "$plist" ]; then
    launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "removed LaunchAgent $plist"
  else
    echo "no LaunchAgent found (already removed)"
  fi
}

remove_service_linux() {
  local unit="$HOME/.config/systemd/user/fri-operator.service"
  if [ -f "$unit" ]; then
    systemctl --user disable --now fri-operator.service 2>/dev/null || true
    rm -f "$unit"
    systemctl --user daemon-reload 2>/dev/null || true
    echo "removed systemd --user service fri-operator"
  else
    echo "no systemd --user service found (already removed)"
  fi
}

remove_updater() {
  if [ -f "$BIN_DIR/fri-update" ]; then
    rm -f "$BIN_DIR/fri-update"
    echo "removed $BIN_DIR/fri-update"
  else
    echo "no fri-update helper found"
  fi
}

purge_checkout() {
  say "Remove the code at $DEST"
  echo "Recordings under FRI_EXPERIMENTS_ROOT (e.g. your Dropbox folder) are NOT touched."
  if [ -d "$DEST/backend/experiments" ] && [ ! -L "$DEST/backend/experiments" ]; then
    echo "!! $DEST/backend/experiments is a real folder (not a symlink) and would be deleted with"
    echo "   the checkout. If it holds recordings, move it out first or skip --purge."
  fi
  printf 'Type the word "remove" to delete %s: ' "$DEST"
  local ans=""
  read -r ans < /dev/tty || ans=""
  if [ "$ans" = "remove" ]; then
    rm -rf "$DEST"
    echo "removed $DEST"
  else
    echo "kept $DEST (nothing deleted)"
  fi
}

uninstall_main() {
  local purge=0 arg
  for arg in "$@"; do
    [ "$arg" = "--purge" ] && purge=1
  done

  say "Background service"
  case "$(uname -s)" in
    Darwin) remove_service_macos ;;
    Linux)  remove_service_linux ;;
    *) echo "unknown OS ($(uname -s)); remove the service manually" ;;
  esac

  say "fri-update helper"
  remove_updater

  if [ "$purge" = "1" ]; then
    purge_checkout
  fi

  say "Done"
  if [ "$purge" = "1" ]; then
    echo "Operator removed. Any recordings under FRI_EXPERIMENTS_ROOT were left in place."
  else
    echo "Service and helper removed. The code ($DEST), recordings, and credentials are untouched."
    echo "To also remove the code:  bash \"$DEST/uninstall.sh\" --purge"
  fi
}

if [ "${FRI_UNINSTALL_LIB:-}" != "1" ]; then
  uninstall_main "$@"
fi
