#!/usr/bin/env bash
# FLIR Research Interface — one-command operator install for macOS (Apple Silicon).
#   curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh | bash
# or, from a checkout:  ./install.sh
# Idempotent: re-running updates the checkout and restarts the service. Never prints secrets.
set -euo pipefail

REPO="https://github.com/mattlmccoy/flir-research-interface.git"
DEST="${FRI_HOME:-$HOME/flir-research-interface}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer automates macOS. For Linux/Windows follow docs/installation.md." >&2; exit 1
fi

say "Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh (install it, then re-run)." >&2; exit 1
fi

say "Tools (uv, ffmpeg@6, libomp, libusb, git)"
export HOMEBREW_NO_AUTO_UPDATE=1
brew list uv >/dev/null 2>&1 || brew install uv
brew list ffmpeg@6 >/dev/null 2>&1 || brew install ffmpeg@6
brew list libomp >/dev/null 2>&1 || brew install libomp
brew list libusb >/dev/null 2>&1 || brew install libusb
command -v git >/dev/null 2>&1 || xcode-select --install

say "Checkout at $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only
elif [ -f "./backend/pyproject.toml" ] && [ -d "./.git" ]; then
  DEST="$(pwd)"; echo "using this checkout"
else
  git clone "$REPO" "$DEST"
fi

say "Python environment"
( cd "$DEST/backend" && uv sync --inexact -q )

say "Spinnaker SDK (PySpin)"
( cd "$DEST/backend" && uv run fri-sdk-check ) || true
echo "If PySpin is not importable: download the Spinnaker 4.4 Apple Silicon .dmg from"
echo "  https://www.teledynevisionsolutions.com/products/spinnaker-sdk/  (free account),"
echo "install the .pkg, then re-run this script; it installs the bundled PySpin wheel."
WHEEL_TGZ=$(ls /Applications/Spinnaker/PySpin/spinnaker_python-*-cp312-cp312-macosx_*_arm64.tar.gz 2>/dev/null | head -1 || true)
if [ -n "$WHEEL_TGZ" ] && ! ( cd "$DEST/backend" && uv run python -c "import PySpin" 2>/dev/null ); then
  TMP=$(mktemp -d); tar -xzf "$WHEEL_TGZ" -C "$TMP"
  ( cd "$DEST/backend" && uv pip install -q "$TMP"/*.whl ) && echo "PySpin installed from $WHEEL_TGZ"
fi

say "Camera credentials + background service"
# When piped through `curl | bash`, stdin is the script itself: take the prompts from the terminal.
if [ -t 0 ]; then
  ( cd "$DEST/backend" && uv run fri-install "$@" )
else
  ( cd "$DEST/backend" && uv run fri-install "$@" < /dev/tty )
fi

say "Done"
echo "Open https://mattlmccoy.github.io/flir-research-interface/ in this Mac's browser: it will find the"
echo "operator at http://127.0.0.1:8000 by itself. Re-run this same command any time to update."
