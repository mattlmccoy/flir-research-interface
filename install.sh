#!/usr/bin/env bash
# FLIR Research Interface — one-command operator install for macOS (Apple Silicon).
#   curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh | bash
# or, from a checkout:  ./install.sh
# Idempotent: re-running updates the checkout and restarts the service. Never prints secrets.
set -euo pipefail

REPO="https://github.com/mattlmccoy/flir-research-interface.git"
DEST="${FRI_HOME:-$HOME/flir-research-interface}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

SDK_BASE="${FRI_SDK_BASE_URL:-https://github.com/mattlmccoy/flir-research-interface/releases/download/sdk-4.4.0.246}"
TELEDYNE="https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"
OS="$(uname -s)"
if [ "$OS" = "Linux" ]; then
  exec bash -c "$(sed -n '/^# ---- linux ----$/,$p' "$0" 2>/dev/null || true)" -- "$@" 2>/dev/null || true
fi
if [ "$OS" != "Darwin" ]; then
  echo "Use install.ps1 on Windows (irm .../install.ps1 | iex)." >&2; exit 1
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
MAC_DMG="${FRI_MAC_DMG:-SpinnakerSDK_FULL_4.4.0.246_arm64.dmg}"
if ! ( cd "$DEST/backend" && uv run python -c "import PySpin" 2>/dev/null ); then
  if [ ! -d /Applications/Spinnaker ]; then
    TMP=$(mktemp -d)
    echo "downloading $MAC_DMG from the internal mirror ($SDK_BASE)…"
    if curl -fL --progress-bar -o "$TMP/$MAC_DMG" "$SDK_BASE/$MAC_DMG"; then
      MNT=$(hdiutil attach -nobrowse -readonly "$TMP/$MAC_DMG" | awk -F'\t' '/\/Volumes\//{print $NF}' | tail -1)
      PKG=$(ls "$MNT"/*.pkg 2>/dev/null | head -1)
      if [ -n "$PKG" ]; then
        echo "installing $PKG (asks for your Mac password)…"
        sudo installer -pkg "$PKG" -target / || true
      fi
      hdiutil detach "$MNT" -quiet || true
    else
      echo "Could not fetch the SDK from the mirror. Download 'Spinnaker 4.4 (macOS Apple Silicon)' from"
      echo "  $TELEDYNE  (free account), install the .pkg, then re-run this command."
    fi
  fi
  WHEEL_TGZ=$(ls /Applications/Spinnaker/PySpin/spinnaker_python-*-cp312-cp312-macosx_*_arm64.tar.gz 2>/dev/null | head -1 || true)
  if [ -z "$WHEEL_TGZ" ]; then
    TMP=${TMP:-$(mktemp -d)}
    curl -fsL -o "$TMP/pyspin-mac.tar.gz" "$SDK_BASE/spinnaker_python-4.4.0.246-cp312-cp312-macosx_14_0_arm64.tar.gz" && WHEEL_TGZ="$TMP/pyspin-mac.tar.gz" || true
  fi
  if [ -n "$WHEEL_TGZ" ]; then
    TMP2=$(mktemp -d); tar -xzf "$WHEEL_TGZ" -C "$TMP2"
    ( cd "$DEST/backend" && uv pip install -q "$TMP2"/*.whl ) && echo "PySpin installed from $WHEEL_TGZ"
  fi
fi
( cd "$DEST/backend" && uv run fri-sdk-check ) || true

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

exit 0
# ---- linux ----
set -euo pipefail
REPO="https://github.com/mattlmccoy/flir-research-interface.git"
DEST="${FRI_HOME:-$HOME/flir-research-interface}"
SDK_BASE="${FRI_SDK_BASE_URL:-https://github.com/mattlmccoy/flir-research-interface/releases/download/sdk-4.4.0.246}"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say "Tools (apt: git, ffmpeg, build deps) + uv"
sudo apt-get update -qq && sudo apt-get install -y -qq git ffmpeg curl libusb-1.0-0 libomp5 2>/dev/null || sudo apt-get install -y -qq git ffmpeg curl libusb-1.0-0
command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh | sh && export PATH="$HOME/.local/bin:$PATH")
export PATH="$HOME/.local/bin:$PATH"
say "Checkout at $DEST"
if [ -d "$DEST/.git" ]; then git -C "$DEST" pull --ff-only; else git clone "$REPO" "$DEST"; fi
( cd "$DEST/backend" && uv sync --inexact -q )
say "Spinnaker SDK"
CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}"); ARCH=$(dpkg --print-architecture)
if ! ( cd "$DEST/backend" && uv run python -c "import PySpin" 2>/dev/null ); then
  TMP=$(mktemp -d)
  PKG="spinnaker-4.4.0.246-${CODENAME}-${ARCH}-pkg.tar.gz"
  if curl -fL --progress-bar -o "$TMP/$PKG" "$SDK_BASE/$PKG"; then
    tar -xzf "$TMP/$PKG" -C "$TMP"; ( cd "$TMP"/spinnaker-* && sudo dpkg -i lib*.deb spinnaker*.deb 2>/dev/null || sudo apt-get -f install -y )
  else
    echo "SDK not on the mirror for ${CODENAME}/${ARCH}; download it from https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"
  fi
  PYARCH=$([ "$ARCH" = "arm64" ] && echo aarch64 || echo x86_64)
  WHL="spinnaker_python-4.4.0.246-cp312-cp312-linux_${PYARCH}.tar.gz"
  if curl -fsL -o "$TMP/$WHL" "$SDK_BASE/$WHL"; then
    mkdir -p "$TMP/py" && tar -xzf "$TMP/$WHL" -C "$TMP/py" && ( cd "$DEST/backend" && uv pip install -q "$TMP"/py/*.whl )
  fi
fi
( cd "$DEST/backend" && uv run fri-sdk-check ) || true
say "Camera credentials"
( cd "$DEST/backend" && uv run fri-install --no-service < /dev/tty )
say "Background service (systemd --user)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/fri-operator.service" <<UNIT
[Unit]
Description=FLIR Research Interface operator
[Service]
WorkingDirectory=$DEST/backend
ExecStart=$(command -v uv) run --directory $DEST/backend fri-serve --host 127.0.0.1 --port 8000 --site-origin https://mattlmccoy.github.io
Restart=always
RestartSec=2
[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload && systemctl --user enable --now fri-operator.service
loginctl enable-linger "$USER" 2>/dev/null || true
say "Done"
echo "Open https://mattlmccoy.github.io/flir-research-interface/ on this machine; it finds the operator at http://127.0.0.1:8000 by itself."
