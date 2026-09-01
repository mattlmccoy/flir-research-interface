# FLIR Research Interface

Cross-platform acquisition, recording, visualization, and analysis software for FLIR
A50/A70 radiometric thermal cameras (GigE Vision / GenICam via the FLIR Spinnaker SDK),
built for RF-heating experiments on polymer powder and intended to replace day-to-day use of
FLIR Research Studio.

**Status: Milestone 0/1 (feasibility + camera probe).** There is no UI yet. What exists:

| Piece | Location | State |
|---|---|---|
| Hardware abstraction (`CameraBackend`, `Frame`) | `backend/flir_research_interface/camera/base.py` | tested |
| Simulated camera (uniform / gradient / hotspot ramp scenes) | `backend/flir_research_interface/camera/simulated.py` | tested |
| FLIR temperature-linear counts to °C conversion | `backend/flir_research_interface/radiometry/temperature_linear.py` | tested, hardware-unverified |
| Milestone-1 camera probe (`fri-probe`) | `backend/flir_research_interface/probe.py`, `scripts/camera_probe.py` | simulated path tested; **PySpin path not yet run on hardware** |
| Spinnaker backend | `backend/flir_research_interface/camera/spinnaker.py` | placeholder, gated on probe output |
| Docs | `docs/` | architecture, radiometry (evidence-only), installation |

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
