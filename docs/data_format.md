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

## Exports (Milestone 7)

All exports are derived from the read-only reader; the Zarr store is never modified.

| Export | Where | Content |
|---|---|---|
| ROI series CSV | `GET /api/experiments/{name}/export/series.csv?rois=…` (playback rail → export) | `t_s, frame_id, S<n>_value, R<n>_mean/min/max` per frame; `#` header lines list units and the ROI geometry |
| Frame CSV | `GET …/frames/{i}/export?format=csv` | °C grid (rows = y, top first); raw counts if the run is not temperature-linear |
| Frame TIFF | `format=tiff` | 32-bit float °C (uint16 counts if not temperature-linear) |
| Frame PNG | `format=png` | 16-bit raw counts |
| Frame NPY | `format=npy` | uint16 raw counts |
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
