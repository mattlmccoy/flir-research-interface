# Development

## Workflow

* Red-green TDD for all testable logic (`backend/tests`). Write the failing test first.
* `uv run pytest` – unit tests (no hardware). `uv run pytest --hardware` – also run tests marked
  `hardware` (need PySpin and a reachable camera; they change `IRFormat`/`PixelFormat` temporarily
  and restore them).
* `uv run ruff check . && uv run ruff format .` – lint/format. `uv run mypy flir_research_interface` – types (strict).
* Only `camera/spinnaker.py` and `probe.py` may import PySpin. Everything else consumes
  `CameraBackend`/`Frame`.
* Conventional Commits; small, reviewable diffs; never commit FLIR binaries, probe outputs, or
  experiment data (see `.gitignore`).

## Simulated camera

```python
from flir_research_interface.camera import create_backend
from flir_research_interface.camera.simulated import HotspotRampScene

cam = create_backend("simulated", scene=HotspotRampScene(
    background_c=25, start_c=25, end_c=200, ramp_s=60, center_xy=(320, 240), radius_px=40))
cam.connect(cam.enumerate()[0])
frame = next(cam.frames())        # Frame.counts is uint16 temperature-linear (10 mK) by default
```

Scenes: `UniformScene`, `GradientScene`, `HotspotRampScene`. Add `noise_k=0.05, seed=1` for
deterministic noise, `realtime=True` to pace at `fps`.

## Milestone gates

| Milestone | Gate to pass before starting |
|---|---|
| 2 Radiometry validation | `probe_report.json` from the real A70 reviewed; node names confirmed |
| 3 Live view | Milestone 2 results in `docs/validation.md` |
| 4 Recording | storage format decision recorded in `docs/data_format.md` |
