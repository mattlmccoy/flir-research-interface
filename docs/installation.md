# Installation and running the camera probe

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

PySpin is **not on PyPI** and Spinnaker is proprietary; both must be downloaded from Teledyne
FLIR (free account): <https://www.teledynevisionsolutions.com/products/spinnaker-sdk/>.

### Pick the right build (facts from the Spinnaker release notes, fetched 2026-09-01)

| Host | Spinnaker | PySpin wheel |
|---|---|---|
| macOS Apple Silicon (this Mac, arm64) | **4.4.x** (Apple Silicon support since 4.1.0.157; "For Intel-based Macs (up to macOS 11.6), use version 3.2") | `spinnaker_python-4.4.x-cp312-cp312-macosx_*_arm64.whl` (or cp310/cp311) |
| macOS Intel | 3.2.x (last Intel release) | cp3x x86_64 wheel |
| Windows 11 x64 | 4.4.x | cp310/311/312 win_amd64 |
| Linux Ubuntu 22.04 x64 / arm64 | 4.4.x | cp310/311/312 linux |

**Already on this Mac:** `/Applications/Spinnaker` 3.1.0.79, an Intel-only (x86_64) build with
PySpin wheels for Python 3.6–3.8. It cannot be imported by any installed interpreter and must be
replaced (run the `uninstall_spinnaker.sh` script from the old DMG first, then install 4.4.x).

### macOS steps

```bash
brew install pkg-config libomp libusb           # Spinnaker README prerequisites
# 1. Install the Spinnaker .pkg (4.4.x, Apple Silicon) from the downloaded DMG.
# 2. Install the matching PySpin wheel into this project's venv:
cd backend
uv pip install /path/to/spinnaker_python-4.4.*-cp312-cp312-macosx_*_arm64.whl
# 3. Verify:
uv run python -c "import PySpin; s=PySpin.System.GetInstance(); v=s.GetLibraryVersion(); print(v.major, v.minor, v.type, v.build); s.ReleaseInstance()"
```

If the wheel targets a different Python minor version, recreate the venv with that version:
`uv venv --python 3.11 .venv && uv sync --extra dev`.

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
