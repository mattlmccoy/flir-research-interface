#!/usr/bin/env bash
# FLIR Research Interface — one-command operator install for macOS (Apple Silicon) and Linux.
#   curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh | bash
# or, from a checkout:  ./install.sh
# Idempotent: re-running updates the checkout and restarts the service. Never prints secrets.
# Sourceable for tests with FRI_INSTALL_LIB=1 (defines the functions without running anything).
set -euo pipefail

REPO="https://github.com/mattlmccoy/flir-research-interface.git"
DEST="${FRI_HOME:-$HOME/flir-research-interface}"
SDK_BASE="${FRI_SDK_BASE_URL:-https://github.com/mattlmccoy/flir-research-interface/releases/download/sdk-4.4.0.246}"
TELEDYNE="https://www.teledynevisionsolutions.com/products/spinnaker-sdk/"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- Linux ----
# Which system package manager this distro uses (apt/dnf/pacman/zypper), or "none".
detect_pkg_mgr() {
  local m
  for m in apt-get dnf pacman zypper; do
    if command -v "$m" >/dev/null 2>&1; then echo "$m"; return 0; fi
  done
  echo none
}

# Best-effort install of the operator's runtime deps. Loud on anything it cannot do; never silent.
linux_install_deps() {
  local mgr; mgr="$(detect_pkg_mgr)"
  case "$mgr" in
    apt-get)
      sudo apt-get update -qq || true
      sudo apt-get install -y git curl libusb-1.0-0 libgomp1 || true
      sudo apt-get install -y ffmpeg || echo "!! ffmpeg did not install via apt; install it manually"
      ;;
    dnf)
      sudo dnf install -y git curl libgomp || true
      # libusb-1.0 is 'libusb1' on current Fedora, 'libusbx' on older releases.
      sudo dnf install -y libusb1 || sudo dnf install -y libusbx || true
      # Full ffmpeg needs RPM Fusion; ffmpeg-free (default repos) is the fallback.
      sudo dnf install -y ffmpeg || sudo dnf install -y ffmpeg-free || {
        echo "!! ffmpeg could not be installed from your repos."
        echo "   Enable RPM Fusion (https://rpmfusion.org) then: sudo dnf install ffmpeg"
      }
      ;;
    pacman)
      sudo pacman -Sy --noconfirm git curl ffmpeg libusb gcc-libs || echo "!! pacman deps incomplete"
      ;;
    zypper)
      sudo zypper --non-interactive install git curl ffmpeg libusb-1_0-0 libgomp1 \
        || echo "!! zypper deps incomplete"
      ;;
    none)
      echo "!! No supported package manager (apt/dnf/pacman/zypper) was found."
      echo "   Install these yourself, then re-run: git, ffmpeg, curl, libusb-1.0, libgomp."
      return 1
      ;;
  esac
}

# Camera driver (PySpin). Auto-installed only on Debian/Ubuntu (Teledyne ships .deb); on other
# distros the operator still installs and runs in SIMULATED mode, with a clear pointer to the SDK.
linux_install_sdk() {
  if ( cd "$DEST/backend" && uv run python -c "import PySpin" 2>/dev/null ); then
    echo "PySpin already importable"; return 0
  fi
  local arch pyarch tmp
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) pyarch=x86_64 ;;
    aarch64|arm64) pyarch=aarch64 ;;
    *) pyarch="$arch" ;;
  esac
  tmp="$(mktemp -d)"
  if command -v dpkg >/dev/null 2>&1; then
    local codename debarch pkg
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")"
    debarch="$(dpkg --print-architecture)"
    pkg="spinnaker-4.4.0.246-${codename}-${debarch}-pkg.tar.gz"
    if curl -fL --progress-bar -o "$tmp/$pkg" "$SDK_BASE/$pkg"; then
      tar -xzf "$tmp/$pkg" -C "$tmp"
      ( cd "$tmp"/spinnaker-* && sudo dpkg -i lib*.deb spinnaker*.deb 2>/dev/null \
        || sudo apt-get -f install -y ) || true
    else
      echo "!! Spinnaker .deb not on the mirror for ${codename}/${debarch}; get it from $TELEDYNE"
    fi
  else
    local pretty; pretty="$(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-Linux}")"
    echo "!! ${pretty} is not Debian/Ubuntu, so the Spinnaker camera SDK is not auto-installed."
    echo "   The operator will still install and run in SIMULATED mode. For the real FLIR A70,"
    echo "   install the Linux Spinnaker SDK from:"
    echo "     $TELEDYNE"
    echo "   then re-run this command to pick up PySpin."
  fi
  # Try the Python wheel regardless — it imports once libSpinnaker*.so is present from the SDK.
  local whl="spinnaker_python-4.4.0.246-cp312-cp312-linux_${pyarch}.tar.gz"
  if curl -fsL -o "$tmp/$whl" "$SDK_BASE/$whl"; then
    mkdir -p "$tmp/py" && tar -xzf "$tmp/$whl" -C "$tmp/py" \
      && ( cd "$DEST/backend" && uv pip install -q "$tmp"/py/*.whl ) || true
  fi
}

linux_main() {
  say "System dependencies"
  linux_install_deps || echo "some system packages are missing; the doctor report below lists them"

  command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh | sh)
  export PATH="$HOME/.local/bin:$PATH"

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

  say "Spinnaker SDK (PySpin) — camera driver"
  linux_install_sdk
  ( cd "$DEST/backend" && uv run fri-sdk-check ) || true

  say "Camera credentials + background service (systemd --user)"
  # When piped through `curl | bash`, stdin is the script itself: take the prompts from the terminal.
  if [ -t 0 ]; then
    ( cd "$DEST/backend" && uv run fri-install "$@" )
  else
    ( cd "$DEST/backend" && uv run fri-install "$@" < /dev/tty )
  fi

  say "Done"
  echo "Open https://mattlmccoy.github.io/flir-research-interface/ on this machine's browser: it"
  echo "finds the operator at http://127.0.0.1:8000 by itself. Re-run this command any time to update."
}

# ---------------------------------------------------------------- macOS ----
mac_main() {
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
  local MAC_DMG="${FRI_MAC_DMG:-Spinnaker-4.4.0.246.dmg}"
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
}

main() {
  local OS; OS="$(uname -s)"
  case "$OS" in
    Darwin) mac_main "$@" ;;
    Linux)  linux_main "$@" ;;
    *) echo "Use install.ps1 on Windows (irm .../install.ps1 | iex)." >&2; exit 1 ;;
  esac
}

# Run unless sourced by a test (FRI_INSTALL_LIB=1). No `$0`/sed self-parsing: that broke under
# `curl | bash`, where $0 is "bash" and the script silently did nothing.
if [ "${FRI_INSTALL_LIB:-}" != "1" ]; then
  main "$@"
fi
