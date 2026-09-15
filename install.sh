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
RAW_INSTALL="https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh"
BIN_DIR="${FRI_BIN_DIR:-$HOME/.local/bin}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Leave an easy, persistent re-run command on the machine. The long curl one-liner scrolls out of
# the terminal after setup; `fri-update` (and the local install.sh) stay put. fri-update pulls the
# latest and re-runs, so it also upgrades the installer itself.
install_updater() {
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/fri-update" <<EOF
#!/usr/bin/env bash
# Update the FLIR Research Interface operator to the latest version and restart it.
set -e
FRI_HOME="\${FRI_HOME:-$DEST}"
git -C "\$FRI_HOME" pull --ff-only || true
exec bash "\$FRI_HOME/install.sh" "\$@"
EOF
  chmod +x "$BIN_DIR/fri-update"
}

# Printed at the end of every install so the re-run/uninstall commands never "disappear".
print_persistent_commands() {
  say "Update or re-run any time (these stay on the machine)"
  echo "  fri-update"
  echo "      or:  bash \"$DEST/install.sh\""
  echo "      or:  curl -fsSL $RAW_INSTALL | bash"
  echo "  Uninstall:  bash \"$DEST/uninstall.sh\"   (add --purge to also remove the code)"
  case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *) echo ""
       echo "  Note: $BIN_DIR is not on your PATH yet — for the short 'fri-update' command, add it:"
       echo "        echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc" ;;
  esac
}

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
      # binutils (ar) + zstd let us unpack the Spinnaker .deb libraries on a non-Debian distro.
      sudo dnf install -y git curl libgomp binutils zstd || true
      # libusb-1.0 is 'libusb1' on current Fedora, 'libusbx' on older releases.
      sudo dnf install -y libusb1 || sudo dnf install -y libusbx || true
      # Full ffmpeg (RPM Fusion) has the libx264 encoder that mp4 export needs. Fedora's default
      # 'ffmpeg-free' can play/decode and make GIFs, but has NO libx264, so mp4 export fails on it.
      if sudo dnf install -y ffmpeg; then
        :
      elif sudo dnf install -y ffmpeg-free; then
        echo "!! Installed 'ffmpeg-free' (default repos). GIF export works; mp4/H.264 export does NOT"
        echo "   (no libx264). For mp4, enable RPM Fusion then swap to the full build:"
        echo "     sudo dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm"
        echo "     sudo dnf install -y --allowerasing ffmpeg"
      else
        echo "!! ffmpeg could not be installed. Enable RPM Fusion (https://rpmfusion.org), then:"
        echo "     sudo dnf install -y ffmpeg"
      fi
      ;;
    pacman)
      sudo pacman -Sy --noconfirm git curl ffmpeg libusb gcc-libs binutils zstd \
        || echo "!! pacman deps incomplete"
      ;;
    zypper)
      sudo zypper --non-interactive install git curl ffmpeg libusb-1_0-0 libgomp1 binutils zstd \
        || echo "!! zypper deps incomplete"
      ;;
    none)
      echo "!! No supported package manager (apt/dnf/pacman/zypper) was found."
      echo "   Install these yourself, then re-run: git, ffmpeg, curl, libusb-1.0, libgomp."
      return 1
      ;;
  esac
}

# Map `uname -m` to the arch tags used by the SDK filenames.
_spin_arch() {  # -> "<pyarch> <debarch>"
  case "$(uname -m)" in
    x86_64|amd64) echo "x86_64 amd64" ;;
    aarch64|arm64) echo "aarch64 arm64" ;;
    *) echo "$(uname -m) $(uname -m)" ;;
  esac
}

# Install the Spinnaker C++ runtime libraries on a NON-Debian distro (Fedora/Arch/openSUSE) by
# extracting them straight out of Teledyne's Ubuntu .deb packages — no dpkg needed. The libs are
# glibc-forward-compatible, so the Ubuntu 24.04 (noble, gcc13) build runs on newer Fedora. They go
# to /opt/spinnaker/lib with an ld.so.conf.d entry, exactly where Teledyne's own installer puts
# them, so the PySpin wheel finds them by soname after ldconfig.
_extract_spinnaker_libs_from_deb() {
  local debarch="$1" tmp="$2"
  if ! command -v ar >/dev/null 2>&1 || ! command -v zstd >/dev/null 2>&1; then
    echo "!! need 'ar' (binutils) and 'zstd' to unpack the SDK libraries; install them and re-run"
    return 1
  fi
  local pkg="spinnaker-4.4.0.246-noble-${debarch}-pkg.tar.gz"
  echo "fetching Spinnaker runtime libraries ($pkg)…"
  if ! curl -fL --progress-bar -o "$tmp/sdk.tar.gz" "$SDK_BASE/$pkg"; then
    echo "!! could not download $pkg from the mirror ($SDK_BASE)"; return 1
  fi
  tar -xzf "$tmp/sdk.tar.gz" -C "$tmp"
  local sdkdir d deb x
  sdkdir="$(echo "$tmp"/spinnaker-*-"${debarch}")"
  # These carry every .so the PySpin extension links: libSpinnaker, libSpinnaker_C, libSpinVideo,
  # libSpinVideo_C, libGenTL, and libSpinUpdate (from the 'spinupdate' package — _PySpin needs it).
  for d in libgentl libspinnaker libspinnaker-c libspinvideo libspinvideo-c spinupdate; do
    deb="$(ls "$sdkdir/${d}_"*.deb 2>/dev/null | head -1)"
    [ -n "$deb" ] || continue
    x="$(mktemp -d)"
    ( cd "$x" && ar x "$deb" && zstd -dc data.tar.zst | sudo tar -x -C / ) \
      || { echo "!! failed to unpack $d"; return 1; }
  done
  sudo ldconfig
  # FLIR's libSpinnaker.so / libSpinVideo.so are marked with an executable stack, which hardened
  # Fedora/SELinux kernels refuse to load ("cannot enable executable stack"). Clear that flag.
  if [ -f "$DEST/scripts/clear_execstack.py" ]; then
    sudo python3 "$DEST/scripts/clear_execstack.py" /opt/spinnaker/lib/*.so* || {
      echo "!! could not clear the executable-stack flag automatically. If 'import PySpin' fails"
      echo "   with 'cannot enable executable stack', run:"
      echo "     sudo dnf install -y execstack && sudo execstack -c /opt/spinnaker/lib/*.so*"
    }
  fi
  _link_ffmpeg_compat
  echo "installed Spinnaker libraries to /opt/spinnaker/lib"
}

# libSpinVideo (pulled in by the PySpin extension) links the ffmpeg 6 sonames; Fedora ships
# ffmpeg 7. Point the names it wants at whatever ffmpeg is installed so the loader can resolve
# libSpinVideo. We never call SpinVideo (its one symbol in _PySpin is a lazily-bound constructor),
# so any ABI drift on that unused path never executes.
_link_ffmpeg_compat() {
  local want base sys
  for want in libavcodec.so.60 libavutil.so.58 libavformat.so.60 libswscale.so.7; do
    [ -e "/opt/spinnaker/lib/$want" ] && continue
    base="${want%.so.*}.so."
    sys="$(ldconfig -p 2>/dev/null | awk -v b="$base" '$1 ~ b {print $NF; exit}')"
    if [ -n "$sys" ] && [ -e "$sys" ]; then
      sudo ln -sf "$sys" "/opt/spinnaker/lib/$want"
      echo "linked $want -> $sys (ffmpeg compat for the unused SpinVideo path)"
    else
      echo "!! no system $base* found to satisfy libSpinVideo; install ffmpeg if PySpin import"
      echo "   later complains about $want"
    fi
  done
  sudo ldconfig
}

# Install the PySpin wheel into the operator venv. The wheel is arch-specific; we look on the SDK
# mirror first, then for a copy the user already downloaded from Teledyne (~/Downloads or the cwd),
# whether still a .tar.gz or already unpacked. Returns non-zero (with guidance) if none is found.
_install_pyspin_wheel() {
  local pyarch="$1" tmp="$2"
  local tgz="spinnaker_python-4.4.0.246-cp312-cp312-linux_${pyarch}.tar.gz"
  local src="" whl=""
  if curl -fsL -o "$tmp/py.tar.gz" "$SDK_BASE/$tgz"; then
    src="$tmp/py.tar.gz"
  else
    # A copy the user downloaded from Teledyne (Keenan's case): the tarball or an unpacked folder.
    src="$(ls "$HOME/Downloads/$tgz" "$PWD/$tgz" 2>/dev/null | head -1 || true)"
    if [ -z "$src" ]; then
      whl="$(ls "$HOME/Downloads/spinnaker_python-4.4.0.246-cp312-cp312-linux_${pyarch}"/*.whl \
               "$HOME/Downloads"/spinnaker_python-*-cp312-cp312-linux_"${pyarch}".whl 2>/dev/null \
             | head -1 || true)"
    fi
  fi
  if [ -n "$src" ]; then
    mkdir -p "$tmp/py" && tar -xzf "$src" -C "$tmp/py"
    whl="$(ls "$tmp"/py/*.whl "$tmp"/py/**/*.whl 2>/dev/null | head -1 || true)"
  fi
  if [ -z "$whl" ]; then
    echo "!! PySpin wheel not found on the mirror or in ~/Downloads."
    echo "   Download 'Spinnaker Python 4.4.0.246' (cp312, linux_${pyarch}) from:"
    echo "     $TELEDYNE"
    echo "   save it to ~/Downloads, then run: fri-update"
    return 1
  fi
  ( cd "$DEST/backend" && uv pip install -q "$whl" ) && echo "PySpin installed from $(basename "$whl")"
}

# Camera driver (PySpin), all distros: install the C++ libs (dpkg on Debian/Ubuntu; extract-to-
# /opt on others) then the Python wheel. If the wheel can't be found, the operator still runs in
# SIMULATED mode and the message says exactly how to finish.
linux_install_sdk() {
  if ( cd "$DEST/backend" && uv run python -c "import PySpin" 2>/dev/null ); then
    echo "PySpin already importable"; return 0
  fi
  local pyarch debarch tmp
  read -r pyarch debarch <<<"$(_spin_arch)"
  tmp="$(mktemp -d)"
  if command -v dpkg >/dev/null 2>&1; then
    local codename pkg
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-noble}")"
    pkg="spinnaker-4.4.0.246-${codename}-${debarch}-pkg.tar.gz"
    if curl -fL --progress-bar -o "$tmp/$pkg" "$SDK_BASE/$pkg"; then
      tar -xzf "$tmp/$pkg" -C "$tmp"
      ( cd "$tmp"/spinnaker-* && sudo dpkg -i lib*.deb spinnaker*.deb 2>/dev/null \
        || sudo apt-get -f install -y ) || true
    else
      echo "!! Spinnaker .deb not on the mirror for ${codename}/${debarch}; get it from $TELEDYNE"
    fi
  else
    _extract_spinnaker_libs_from_deb "$debarch" "$tmp" || true
  fi
  _install_pyspin_wheel "$pyarch" "$tmp" || true
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

  install_updater
  say "Done"
  echo "Open https://mattlmccoy.github.io/flir-research-interface/ on this machine's browser: it"
  echo "finds the operator at http://127.0.0.1:8000 by itself."
  print_persistent_commands
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

  install_updater
  say "Done"
  echo "Open https://mattlmccoy.github.io/flir-research-interface/ in this Mac's browser: it will find the"
  echo "operator at http://127.0.0.1:8000 by itself."
  print_persistent_commands
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
