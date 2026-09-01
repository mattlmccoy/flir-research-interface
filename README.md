# FLIR Research Interface

Cross-platform acquisition, recording, visualization, and analysis software for FLIR
A50/A70 radiometric thermal cameras (GigE Vision / GenICam via the FLIR Spinnaker SDK),
built for RF-heating experiments on polymer powder and intended to replace day-to-day use of
FLIR Research Studio.

**Status: Milestone 3 (live view) working against the real A70; Milestone 2 validation table
still open.** `fri-serve` + the React UI show live temperature-linear video at 30 Hz with
setup diagnostics (SDK check, network discovery, connect). No recording yet. What exists:

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
| Docs | `docs/` | architecture, radiometry (from the camera's node map), installation, camera_setup, validation protocol, visible_camera investigation |

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
docs/      architecture.md, radiometry.md, installation.md, development.md
scripts/   camera_probe.py wrapper
frontend/  (empty; React/TypeScript UI starts at Milestone 3)
examples/  (empty; dataset-loading examples arrive with the storage format)
plan/      task plan + research notes for this project (reference downloads are git-ignored)
```

## License

MIT for this repository's own code. FLIR Spinnaker SDK and PySpin are proprietary and are
never redistributed here; install them from Teledyne FLIR.
