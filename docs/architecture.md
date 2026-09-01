# Architecture

## 1. Goal and data-integrity principle

```
FLIR A70  --GigE Vision/GenICam-->  Spinnaker / PySpin  -->  acquisition service (Python)
   -->  scientific storage (time-series of 16-bit frames + metadata)
   -->  REST + WebSocket  -->  browser UI (React/TypeScript)  -->  ROI / plots / export
```

Three data classes are kept strictly apart and are never allowed to overwrite one another:

1. **Camera/radiometric source data** – the 16-bit counts exactly as delivered by the camera
   (`Frame.counts`), plus the `IRFormat`/`PixelFormat` that gives them meaning.
2. **Calibrated temperature data** – derived from (1) by the FLIR-documented rule for the
   active `IRFormat` (`radiometry/temperature_linear.py`). Derivation is pure and repeatable.
3. **Visualization data** – palettes, display ranges, overlays. Produced on demand from (2),
   never stored as the canonical dataset.

Palette, display range, ROI, plot and threshold changes can never modify (1) or (2).

## 2. Repository layout

```
backend/flir_research_interface/
  camera/        hardware abstraction; ONLY place allowed to import PySpin
    base.py        CameraBackend (ABC), Frame, DeviceDescriptor, errors
    simulated.py   SimulatedCameraBackend + scenes (no hardware)
    spinnaker.py   placeholder until the probe has run on the real A70
    __init__.py    registry (CAMERA_BACKENDS) + create_backend() factory
  radiometry/    counts -> temperature, FLIR-documented rules only
  probe.py       Milestone-1 probe (read-only nodemap dump + one frame)
  acquisition/   (M3) acquisition thread, bounded queues, dropped-frame accounting
  recording/     (M4) recorder, finalization, crash recovery
  analysis/      (M6+) ROI statistics, dT/dt, thresholds, maps
  api/           (M3) FastAPI REST + WebSocket
  models/        (M3) pydantic models for API and metadata
backend/tests/   pytest; `hardware` marker deselected unless --hardware
frontend/        (M3) React + TypeScript, Canvas/WebGL image, Plotly plots
docs/            this folder
scripts/         camera_probe.py
```

## 3. Hardware abstraction layer

`CameraBackend` is the only interface the rest of the application sees:

```
enumerate() -> [DeviceDescriptor]     discover; never connects, never changes network settings
connect(descriptor) / disconnect()    lifecycle; disconnect is idempotent
is_connected                          state
camera_info() -> dict                 auditable snapshot, stored with every experiment
frames() -> Iterator[Frame]           blocking generator of frames
```

`Frame` is frozen and carries `frame_id`, `device_timestamp_ns` (SDK/camera timestamp),
`host_timestamp_ns` (`time.time_ns()` at receipt), `pixel_format`, `ir_format`, `counts`
(2-D `uint16`, copied out of the SDK buffer *before* `Image.Release()`), and `incomplete`.

Backends register under a name (`register_backend("simulated")`) so a future
`AravisCameraBackend` or a second SDK can be added without touching callers.

## 4. Acquisition and recording model (planned, Milestone 3–4)

```
   camera thread (PySpin GetNextImage loop; owns SDK buffers; copies + releases)
        |
        +--> recording queue   (bounded, priority; overflow = counted + logged, never silent)
        +--> analysis queue    (bounded; drops are counted separately)
        +--> visualization queue (bounded, newest-wins; drops are expected and counted)
```

Rules: the camera thread never blocks on a consumer; the recording path has priority; every
queue reports its dropped-frame count; the recorder runs inside the service process so a
closed/crashed browser cannot stop a recording.

## 5. Timestamps

Per frame we store the SDK timestamp (`Image.GetTimeStamp()`, documented by PySpin as
nanoseconds), the host receipt time, and `frame_id`. The probe also executes the camera
timestamp latch (`TimestampLatch`/`TimestampLatchValue` or `GevTimestampControlLatch`/
`GevTimestampValue`, whichever the camera exposes) bracketed by host times so the offset
between camera clock and host clock can be measured. Exact tick semantics on the A70 are
UNKNOWN until the probe runs; see `docs/radiometry.md` section 6.

## 6. Storage (decision deferred to Milestone 4)

Candidates: Zarr (chunked `uint16[time, y, x]`, cloud/NumPy friendly), HDF5 (MATLAB-native
via `h5read`), plus JSON metadata, CSV timestamps/events. Requirements that will drive the
choice: append-safe while recording, crash-recoverable, trivial `numpy`/`zarr`/`h5py` load,
MATLAB import path. Raw counts + `IRFormat` are the canonical record; temperature is derived
on load. Whether a second `Radiometric` (signal-linear) stream is worth storing is an open
question that depends on what the camera exposes (see radiometry doc).

## 7. Network model (Milestone 10)

The acquisition machine owns the camera link (GigE/PoE). The UI is served on the LAN,
advertised via mDNS under a configurable hostname (e.g. `flir-research.local`). Binding to
non-loopback interfaces is opt-in and will require at least a shared token; camera control
and file access are never exposed unauthenticated to arbitrary networks. During development
`localhost` is fine.

## 8. Environment facts that shaped this session

* The development Mac is Apple Silicon. The locally installed Spinnaker 3.1.0.79 is an
  Intel-only build with PySpin wheels for Python 3.6–3.8; it cannot be imported here.
  Spinnaker 4.1+ has native Apple Silicon builds, and 4.4.x ships PySpin for Python 3.10–3.12
  (3.9 and older deprecated). The backend therefore targets Python 3.10–3.12 and the venv is 3.12.
* FLIR Research Studio is not installed on this Mac; validation (Milestone 2) needs a machine
  that has it, or the same camera viewed from both tools.
