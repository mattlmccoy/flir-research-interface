# Installation

## 0. Quick start (macOS, Apple Silicon) — one command

```bash
curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh | bash
```

It installs the tools with Homebrew (uv, ffmpeg@6, libomp, libusb), clones or updates the
repository into `~/flir-research-interface`, builds the Python environment, checks for the
Spinnaker SDK and names the exact Teledyne download if it is missing (that one download needs a
free Teledyne login and cannot be automated), installs the bundled PySpin wheel once the SDK is
present, asks for the camera IP and RTSP credentials (stored only in the git-ignored
`backend/.env`, mode 600), and installs a login item (launchd LaunchAgent) that runs the operator
on `http://127.0.0.1:8000` and restarts it if it dies. Then open
<https://mattlmccoy.github.io/flir-research-interface/> in a browser on the same machine and
enter that address once. Re-running the command updates everything.

Useful afterwards:

```bash
cd ~/flir-research-interface/backend
uv run fri-install --doctor      # prerequisite report (never reports unknown as OK)
tail -f operator.log             # operator log
launchctl kickstart -k gui/$(id -u)/io.github.mattlmccoy.flir-research-interface   # restart
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.github.mattlmccoy.flir-research-interface.plist  # uninstall the service
```

Linux: the same steps by hand, then a `systemd --user` unit running
`uv run --directory <checkout>/backend fri-serve --port 8000`. Windows: not yet tested (the code
is portable; PySpin has a Windows wheel); run `uv run fri-serve` from a terminal for now.

## 1. Development toolchain (manual route)

## 1. Development toolchain

* Python 3.10–3.12 (PySpin 4.4 supports these; 3.9 and older are deprecated by Teledyne).
  This repository's venv is Python 3.12.
* [`uv`](https://github.com/astral-sh/uv) for environments (`brew install uv` on macOS).
* Node 18+ / npm (frontend, from Milestone 3; not needed yet).

```bash
cd backend
uv sync --extra dev          # creates backend/.venv (Python 3.12) and installs numpy, pytest, ruff, mypy
uv run pytest                # all tests run without hardware
uv run fri-probe --simulated # exercises the probe report against the simulated camera
```

## 2. FLIR Spinnaker SDK + PySpin (required for the real camera)

PySpin is **not on PyPI** and Spinnaker is proprietary; both come from Teledyne FLIR (free
account): <https://www.teledynevisionsolutions.com/products/spinnaker-sdk/>.

Run the checker first; it detects your OS/CPU/Python and tells you exactly which artifact you
need, whether a local copy exists, and whether PySpin already imports:

```bash
cd backend && uv run fri-sdk-check
```

### Which build (from the Spinnaker 4.4.0.246 downloads and release notes, verified 2026-09-01)

| Host | Spinnaker | PySpin |
|---|---|---|
| macOS Apple Silicon (this Mac) | **4.4.x** .dmg → .pkg (Apple Silicon since 4.1; macOS Sonoma 14+) | **bundled inside the installer**: `/Applications/Spinnaker/PySpin/spinnaker_python-4.4.0.246-cp{38,39,310,312}-*-macosx_*_arm64.tar.gz`. There is no separate macOS PySpin download on the website. |
| macOS Intel | 3.2.x only (last Intel release; PySpin ≤ Python 3.8) | not usable with this project's Python 3.10–3.12 requirement |
| Windows 11 x64 | `SpinnakerSDK_FULL_4.4.0.246_x64.exe` | separate download `spinnaker_python-4.4.0.246-cp3XX-cp3XX-win_amd64.*` |
| Ubuntu 20.04 / 22.04 / 24.04, amd64 or arm64 | `spinnaker-4.4.0.246-{focal,jammy,noble}-{amd64,arm64}-pkg.tar.gz` | separate download `spinnaker_python-4.4.0.246-cp3XX-cp3XX-linux_{x86_64,aarch64}.tar.gz` |

A Linux or Windows wheel will **not** install on macOS (pip rejects the platform tag); use the
bundled macOS tarball.

### macOS steps (what actually worked on this Mac)

```bash
brew install pkg-config libomp libusb ffmpeg@6   # Spinnaker README: "Using a newer version of FFMPEG will result in failure"
# 1. Install the Spinnaker 4.4.x Apple Silicon .pkg from the DMG.
# 2. Extract the bundled wheel matching your venv's Python (3.12 here) and install it:
mkdir -p /tmp/pyspin && tar -xzf /Applications/Spinnaker/PySpin/spinnaker_python-4.4.0.246-cp312-cp312-macosx_14_0_arm64.tar.gz -C /tmp/pyspin
cd backend && uv pip install /tmp/pyspin/spinnaker_python-4.4.0.246-cp312-cp312-macosx_14_0_arm64.whl
uv run fri-sdk-check    # should print "PySpin importable: True (4.4.0.246)"
```

Notes:

* Without `ffmpeg@6` the import fails with `Library not loaded: /opt/homebrew/opt/ffmpeg@6/lib/libswscale.7.dylib`
  (Spinnaker's `libSpinVideo` links against it). Having ffmpeg 7 installed does not help; both can coexist.
* PySpin's README: Python 3.12+ needs NumPy 2.x; Python < 3.12 needs NumPy 1.x.
* `uv sync` removes packages not declared in `pyproject.toml`, which would uninstall PySpin. After
  the wheel is installed, use `uv sync --extra dev --inexact` for dependency updates, or re-run the
  `uv pip install` above.
* If an old Intel Spinnaker 3.x was installed before, its leftover `spinnaker_python-3.1.*` tarballs
  and `README.txt` may remain in `/Applications/Spinnaker`; they are harmless. The libraries in
  `/usr/local/lib` are replaced by the 4.4 installer (verify with `file -L /usr/local/lib/libSpinnaker.dylib` → arm64).

### Local installer cache (`vendor/spinnaker/`, git-ignored)

The Spinnaker EULA (§3) prohibits copying the SDK or providing it to third parties, and its OEM
clause (§4) only permits redistributing runtime binaries as part of a derivative product, with
end-user redistribution prohibited. **Installers, wheels and tarballs are therefore never
committed.** Downloaded artifacts may be kept locally in `vendor/spinnaker/` (ignored by git);
`fri-sdk-check` scans that folder and `/Applications/Spinnaker/PySpin` and reports which file
matches your machine. A future packaged release will ship an installer that detects the platform
and prompts for the matching Teledyne download in the same way.

### Disk space

The acquisition machine needs headroom: 640×480 × 2 bytes × 30 Hz ≈ 18 MB/s ≈ 1.1 GB/min of raw
counts before compression. The development Mac was at 100 % (1.8 GB free) when the SDK install
failed with "No space left on device". Recording will refuse to start below a configurable
free-space threshold (Milestone 4).

## 3. Camera network setup

* Connect the A70 via PoE (IEEE 802.3af class 3) or 24/48 V DC and Gigabit Ethernet to the
  acquisition machine. A dedicated NIC/adapter for the camera is strongly preferred.
* The camera defaults to DHCP; without a DHCP server it should fall back to link-local
  (169.254.x.x), and the host adapter should be set to the same scheme. Spinnaker's own tools
  (SpinView / `AdapterConfig`) can list and force IPs; the probe **never** changes network settings.
* Enable jumbo frames (MTU 9000) on the camera-facing adapter for stable 30 Hz streaming
  (Spinnaker README §3.1: `networksetup -setMTU <iface> 9000` on macOS, temporary).
* Confirm the camera is visible in SpinView before running the probe; if SpinView cannot see
  it, the probe will not either.

## 4. Run the probe against the A70

Default mode is **read-only**: it enumerates, connects, dumps every GenICam node map, latches
the camera clock, grabs one frame in whatever mode the camera is currently in, and cleans up.

```bash
cd backend
uv run fri-probe --output-dir ../probe_output_a70
```

Options:

* `--serial <SN>` choose a camera when several are attached.
* `--set-temperature-linear` **temporarily** sets `PixelFormat=Mono16` and
  `IRFormat=TemperatureLinear10mK`, grabs the frame, then restores the previous values.
  Use it on a second run so we can see both the as-found state and the temperature-linear frame.
* `--timeout-ms 10000` if the first frame times out.
* `-v` for debug logging.

Outputs (in `--output-dir`): `probe_report.json` (everything, including the full node maps) and
`frame_raw.npy` (the raw counts). Both are git-ignored because they contain the serial number.

### What to send back

1. The complete console output of the read-only run.
2. `probe_report.json` from the read-only run.
3. Optionally the same two things from a `--set-temperature-linear` run.
4. Which measurement range Research Studio shows at the time (e.g. "FOL08NOF, -20…250 °C")
   and roughly what the scene temperature was, for a plausibility check.

## 5. Troubleshooting the probe

| Symptom | Likely cause / action |
|---|---|
| `PySpin is not importable` | wheel not installed into `backend/.venv`, or Python version mismatch (`uv run python -V`) |
| `Number of cameras detected: 0` | IP/subnet mismatch, firewall, or camera on another adapter; check SpinView first |
| `GetNextImage` timeout | packet size/MTU issues; try `--timeout-ms 10000`; check jumbo frames both ends |
| `Image incomplete` | packet loss; reduce `GevSCPSPacketSize`/enable jumbo frames; check cable/switch |
| Node map dump shows `error` fields | expected for some vendor nodes; the rest of the dump is still valid |
