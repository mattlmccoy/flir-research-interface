# Experiment data format (Milestone 4 decision)

## Decision: Zarr v2 canonical store, HDF5/CSV/TIFF as exports

| Requirement (brief §18, §22, §28) | Zarr v2 (chosen) | HDF5 (alternative) |
|---|---|---|
| Append while recording at 30 Hz | native resizable arrays, chunk = 32 frames | resizable datasets, fine |
| Crash safety | each chunk is its own file written atomically; a crash loses at most the frames not yet flushed; everything already on disk stays readable with `zarr.open` | a file not closed cleanly can be unreadable unless SWMR/flush discipline is perfect |
| Load in Python | `zarr.open_group(path)["counts"][...]` → NumPy | `h5py` |
| Load in MATLAB | `zarrread` (R2025a+), or via the HDF5 export | `h5read` everywhere |
| Compression | lossless Blosc-zstd level 3 with bit-shuffle (≈2–4× on thermal counts) | gzip/szip |
| Inspectable without tools | yes: JSON metadata + directory of chunks | needs h5dump |

Lossless compression only. Raw `uint16` counts and the `IRFormat` are the canonical record;
temperature is derived on load with the FLIR rule stored in `metadata.json`. Nothing is stored
as 8-bit or colorized (brief §18).

## Layout

```
experiments/
  20260901_193012_PA12_Run_014/
    metadata.json        experiment fields, camera_info (all radiometric settings, cases, object
                         parameters, calibration constants), conversion rule, software version +
                         git commit, host platform, store description
    thermal.zarr/        Zarr v2 group
      counts             uint16 [time, y, x], chunks (32, 480, 640), attrs: ir_format, pixel_format, axes
      frame_id           int64 [time]   camera frame counter (gaps = frames never delivered)
      device_timestamp_ns int64 [time]  camera clock, ns (1 GHz tick, 1 ms granularity on the A70)
      host_timestamp_ns  int64 [time]   time.time_ns() at receipt on the acquisition host
    events.json          recorder events: start, stop, frame_gap, error; user annotations (M8)
    manifest.json        written ONLY on clean stop: frames_received/written, queue_dropped,
                         frame_id_gaps + gap_events, duration, error, complete flag, sha256 of
                         metadata.json and events.json
    preview.png          derived, regenerable: mid-capture frame, iron palette (fri-thumbs)
    keyframes.png        derived, regenerable: 12-frame horizontal strip for hover-scrub
    previews.json        derived, regenerable: sidecar copy of the previews dict (units,
                         preview{}, keyframes{}), written by generate_previews() so an
                         experiment without manifest.json (crash/incomplete) still exposes
                         previews; manifest.json["previews"] takes precedence when both exist
```

An experiment directory **without** `manifest.json` is incomplete (crash or power loss). It is
still readable; `inspect_experiment()` reports `frames_on_disk` and `complete=False`.

`complete` is `True` only when there was no writer error, the recording queue never overflowed
(`queue_dropped == 0`) and every received frame was written. Camera-side gaps (`frame_id_gaps`)
do not make a recording incomplete, but they are listed so that time-series analysis can account
for them.

## Loading

```python
import json, zarr, numpy as np
exp = "experiments/20260901_193012_PA12_Run_014"
meta = json.load(open(f"{exp}/metadata.json"))
g = zarr.open_group(f"{exp}/thermal.zarr", mode="r")
counts = g["counts"]                       # lazy, [time, y, x]
k, off = meta["conversion"]["kelvin_per_count"], meta["conversion"]["kelvin_offset"]
frame_100_c = counts[100].astype(np.float32) * k - off
t_s = (g["device_timestamp_ns"][:] - g["device_timestamp_ns"][0]) / 1e9
```

MATLAB (R2025a+): `counts = zarrread("…/thermal.zarr/counts");` then apply the same rule. For older
MATLAB use the HDF5 export below.

## What one recording contains

```
experiments/<YYYYMMDD_HHMMSS>_<name>/
  thermal.zarr/          every radiometric frame, lossless: counts[t,y,x] uint16 (zstd),
                         frame_id[t], device_timestamp_ns[t], host_timestamp_ns[t]
  metadata.json          written at start: camera identity + every node that affects the
                         measurement (case, emissivity, reflected/atmospheric temperature,
                         distance, humidity, lens, calibration constants), the counts→°C rule,
                         software version + git commit + host, the operator's experiment fields,
                         the ROIs in force (`rois`, with names/colours) and the visible↔IR
                         alignment in force (`visible_alignment`), `nuc_hold` (NUC mode held
                         Off during the run, and whether a NUC ran just before it); post-hoc
                         edits append to `edits`
  events.json            recording start/stop, frame gaps, NUCs, `trigger` / `trigger_end` for
                         armed recordings (the condition that fired, the watched value, the
                         frame id, the number of pre-trigger frames), operator marks (RF ON/OFF,
                         custom) each with the frame id it happened at, and `frozen_frames`
                         runs: the A70 repeats its last image (new frame id and timestamp,
                         identical pixels) for ~2 s while it performs a NUC; those frames are
                         kept but counted (`repeated_frames`, `frozen_runs` in manifest.json
                         and the live status) so a flat stretch in a trace is explained
  manifest.json          written at clean stop: frames written, gaps, drops, complete flag,
                         file checksums, visible-video summary
  visible.mp4 + .json    the visible camera (H.264 stream copy) when "visible video" was ticked,
                         with host-clock start/stop, measured fps and hash
  preview.png, keyframes.png, previews.json   thumbnails (visualization only)
  README.txt             written at stop: the recording described in plain prose (camera,
                         case, object parameters, °C rule, experiment fields, ROIs, marks,
                         which file holds what) for whoever opens the folder later
  exports/roi_plot.png   written at stop when ROIs were stored: every ROI's trace against
                         time (spot value, or mean with a min–max band) with the marks
  exports/roi_series.csv  written automatically at stop: every stored ROI evaluated on every
                         frame (mean/min/max, or value for spots), in °C
  exports/thermal_preview.mp4  rendered automatically after stop (in the background, so the stop
                         itself is instant): the whole run as a small H.264 video, iron palette,
                         one °C scale fixed to the run's min/max, colour bar and elapsed-time
                         label. For viewing and sharing only; re-render any time from playback
                         → export, or `POST /api/experiments/<name>/export/thermal-video`
  exports/<name>.h5      on demand: the whole run as HDF5 for MATLAB / Python
```

Nothing derived is ever written back into `thermal.zarr`. ROI statistics, plots and exports are
recomputed from the raw counts, so ROIs can be redrawn after the fact (playback → "load this
recording's ROIs" restores the recorded set).

## Exports (Milestone 7)

All exports are derived from the read-only reader; the Zarr store is never modified.

| Export | Where | Content |
|---|---|---|
| ROI series CSV | `GET /api/experiments/{name}/export/series.csv?rois=…` (playback rail → export) | `t_s, frame_id, S<n>_value, R<n>_mean/min/max/std` per frame (std = population standard deviation); `#` header lines list units, the ROI geometry and any per-ROI optics (`[emissivity=…, reflected_c=…]`, see docs/radiometry.md) |
| Frame CSV | `GET …/frames/{i}/export?format=csv` | °C grid (rows = y, top first); raw counts if the run is not temperature-linear |
| Frame TIFF | `format=tiff` | 32-bit float °C (uint16 counts if not temperature-linear) |
| Frame PNG | `format=png` | 16-bit raw counts |
| Frame NPY | `format=npy` | uint16 raw counts |
| Thermal preview video | `POST …/export/thermal-video` → `exports/thermal_preview.mp4`; served at `GET …/thermal_preview.mp4` | H.264 (yuv420p, CRF 23, ≤30 fps) of every frame; iron palette on a fixed scale; not radiometric |
| Whole run HDF5 | `POST …/export/hdf5` → `<experiment>/exports/<name>.h5` | `counts` (uint16, gzip, chunked by 32 frames), `t_s`, `frame_id`, `device_timestamp_ns`, `host_timestamp_ns`; attrs `ir_format`, `kelvin_per_count`, `kelvin_offset`, `conversion`, `metadata_json`, `events_json` |

MATLAB:

```matlab
counts = h5read("exports/run.h5", "/counts");        % [x, y, time] in MATLAB's column-major order
k   = h5readatt("exports/run.h5", "/", "kelvin_per_count");
off = h5readatt("exports/run.h5", "/", "kelvin_offset");
t_c = double(counts) * k - off;
```

## Future channels (brief §43)

Additional timestamped channels (RF forward/reflected power, machine events) will be added as
further 1-D arrays or sub-groups in the same store keyed by `host_timestamp_ns`, without changing
the thermal arrays. Visible video (`visible.mp4`, Milestone 9) sits beside the store with its own
per-frame host timestamps.
