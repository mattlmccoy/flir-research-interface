# FLIR Research Interface

Cross-platform acquisition, recording, visualization, and analysis software for FLIR
A50/A70 radiometric thermal cameras (GigE Vision / GenICam via the FLIR Spinnaker SDK),
built for RF-heating experiments on polymer powder and intended to replace day-to-day use of
FLIR Research Studio.

## Use it

**→ [mattlmccoy.github.io/flir-research-interface](https://mattlmccoy.github.io/flir-research-interface/)**

The interface is a web app. It runs against a small local **operator** that talks to the camera on
your machine; the page finds it automatically at `http://127.0.0.1:8000`. Install the operator once
per machine with the one-liner below, then just open the link.

### Install / update / uninstall

| Platform | Install (and update — re-running updates everything) |
|---|---|
| macOS (Apple Silicon) | `curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh \| bash` |
| Linux (Ubuntu, Fedora, Arch, openSUSE) | `curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh \| bash` |
| Windows 10/11 x64 | PowerShell: `irm https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.ps1 \| iex` |

The installer sets up the tools, installs the Spinnaker SDK + PySpin, pre-fills this lab's camera
credentials (just press Enter), and registers a background service. It leaves an easy re-run command
on the machine — **`fri-update`** (or `bash ~/flir-research-interface/install.sh`) — so you never
have to hunt for the long command again.

**Uninstall:** `bash ~/flir-research-interface/uninstall.sh` (add `--purge` to also remove the code;
your recordings are never deleted). Full details and the Linux camera-driver notes are in
[docs/installation.md](docs/installation.md).

**Status: in daily lab use on the A70.** Live view, recording, playback, ROIs and
temperature-vs-time plots, camera controls, exports, event marks and metadata edits, and the
visible-video recorder are all verified on the camera. The web app is deployed to GitHub Pages and
drives a local operator (macOS launchd / Linux systemd / Windows Task Scheduler) installed by the
one-liner above; an in-app banner tells each machine when its operator is behind the site. RF-linked
recording triggers and closed-loop thermal control (FLIR as sensor/recorder, a separate RF session
as the PID) are wired in. `fri-serve` + the React UI show live temperature-linear video at
30 Hz, record lossless Zarr experiments with full frame accounting, replay them without the
camera, measure spots and rectangles live and in playback, write real camera nodes (locked while
recording), and export CSV/TIFF/PNG/NPY/HDF5. What exists:

| Piece | Location | State |
|---|---|---|
| Hardware abstraction (`CameraBackend`, `Frame`) | `backend/flir_research_interface/camera/base.py` | tested |
| Simulated camera (uniform / gradient / hotspot ramp scenes) | `backend/flir_research_interface/camera/simulated.py` | tested |
| FLIR temperature-linear counts to °C conversion | `backend/flir_research_interface/radiometry/temperature_linear.py` | tested; Kelvin scale confirmed on the A70 |
| Milestone-1 camera probe (`fri-probe`) | `backend/flir_research_interface/probe.py`, `scripts/camera_probe.py` | run on the A70; node map, cases, timestamps captured |
| SDK/PySpin platform checker (`fri-sdk-check`) | `backend/flir_research_interface/sdk_install.py` | tested |
| Raw GigE Vision discovery + subnet diagnosis | `backend/flir_research_interface/camera/gvcp.py` | tested against a real A70 reply |
| Spinnaker backend (`SpinnakerCameraBackend`) | `backend/flir_research_interface/camera/spinnaker.py` | **hardware tests pass on the A70** (`pytest --hardware`) |
| Acquisition service + FastAPI/WebSocket API | `backend/flir_research_interface/acquisition/`, `api/` | tested (TestClient), verified live |
| Browser UI (setup + live view, palettes client-side) | `frontend/` (Vite + React + TS) | logic tested with `node --test`; verified in browser against the A70 |
| Recorder (Zarr v2, bounded queue, gaps/drops accounting, disk guard, crash-detectable manifest) | `backend/flir_research_interface/recording/recorder.py` | tested |
| Playback (read-only ExperimentReader, experiment/timeline/frame endpoints, scrub/play/step/speed UI) | `backend/flir_research_interface/playback/`, `frontend/src/components/PlaybackPage.tsx` | tested; store verified unchanged after playback |
| UI system + Studio layout (tokens, tool strip, rail, dock, status bar) | `frontend/src/theme.css`, `frontend/src/components/studio/` | logic tested; verified in browser |
| Experiment previews + hover-scrub cards + reveal in file manager | `backend/.../analysis/preview.py`, `api/reveal.py`, `frontend/src/components/ExperimentCard.tsx` | tested; verified in browser |
| ROIs (spot / rectangle), live traces, whole-recording series + event markers (M6) | `frontend/src/lib/roi.ts`, `plot.ts`, `components/ThermalView.tsx`, `TimePlot.tsx`, `backend/.../analysis/series.py` | tested; verified in browser |
| Camera controls (case, object parameters, NUC mode, frame rate, NUC now; locked while recording) | `backend/.../camera/controls.py`, `frontend/src/components/CameraControls.tsx` | tested; **verified on the A70** (emissivity / reflected temperature written and read back, NUC executed, stream undisturbed) |
| Exports: ROI series CSV, frame CSV/TIFF/PNG/NPY, whole-run HDF5 (M7) | `backend/.../analysis/export.py`, `frontend/src/components/ExportSection.tsx` | tested |
| Event marks during recording + post-hoc metadata edits (M8) | `backend/.../recording/metadata.py`, `frontend/src/components/MetadataEditor.tsx` | tested; verified in browser |
| Visible-camera recorder: ffmpeg stream copy of RTSP `/avc/ch1` beside the thermal store (M9 core) | `backend/.../visible/recorder.py` | tested; **verified on the A70** (valid 1280×960 H.264 beside the store; the camera limits it to ~12 fps while the radiometric stream runs) |
| Docs | `docs/` | architecture, radiometry, installation, camera_setup, validation protocol, data_format, visible_camera |

## Scientific stance

FLIR's factory calibration is the source of truth. The application never fits, approximates,
or reverse-engineers the counts-to-temperature relationship. It uses only the conversion
FLIR documents for the camera's temperature-linear output, and it stops when a step cannot be
supported by FLIR documentation or by direct introspection of the connected camera.
See [docs/radiometry.md](docs/radiometry.md).

## Quick start (no camera)

```bash
cd backend
uv sync --extra dev
uv run pytest
uv run fri-probe --simulated --output-dir /tmp/fri-sim
```

## Probe the real A70

See [docs/installation.md](docs/installation.md). `uv run fri-sdk-check` tells you which
Spinnaker/PySpin artifact your machine needs (on macOS the PySpin wheel is bundled inside the
Spinnaker installer). PySpin 4.4.0.246 is verified importable on this Mac. Connect the camera, then:

```bash
cd backend
uv run fri-probe --output-dir ../probe_output_a70
```

Send back `probe_output_a70/probe_report.json` and the console output. The next development
step (radiometric node selection, live view) is deliberately blocked on that file.

## Layout

```
backend/   Python package `flir_research_interface` + tests (uv-managed)
docs/      architecture, radiometry, installation, camera_setup, validation, data_format, visible_camera, development
scripts/   camera_probe.py wrapper
frontend/  Vite + React + TypeScript UI (built into frontend/dist and served by fri-serve)
examples/  (dataset-loading examples; see docs/data_format.md)
plan/      task plan + research notes for this project (reference downloads are git-ignored)
```

## License

MIT for this repository's own code. FLIR Spinnaker SDK and PySpin are proprietary and are
never redistributed here; install them from Teledyne FLIR.
