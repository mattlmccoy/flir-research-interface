# Media Export editor — design

**Goal:** From playback, open a full-screen editor to export a clip (MP4 + GIF) of a chosen time
window with toggleable overlays and a title, plus a companion ROI-stats plot + CSV for that window.

**Decisions (from the brainstorm):** full-screen editor; **MP4 + GIF**; overlays = ROIs+values,
frame min/max/mean, timestamp/elapsed, colour bar, custom title, and an **animated live-plot inset**
(an ROI's temperature growing over time with a playhead); **stored ROIs**, size (1×/2×) chosen per
export; the ROI-stats plot/CSV is a **separate companion** output for the same window.

---

## What already exists (reuse, don't rebuild)
- `analysis/thermal_video.py`: `thermal_frame_rgb(...)` composes one frame (palette + colour bar +
  elapsed-time label + ROIs-with-values); `render_thermal_video(reader, scale, with_rois,
  on_progress)` encodes the **whole run** to H.264. `encode_command` builds the ffmpeg pipe.
- `analysis/series.py`: `roi_series(reader, rois, ...)` already yields per-frame **min/max/mean/std**
  per area ROI — the data for the stats plot and the live-plot inset.
- Background-job + progress plumbing (`app.state.*_jobs`, poll `…/status`) and the per-run
  `KeyedLocks` (so a render can't race the auto-render/regenerate) — reuse verbatim.
- `radiometry/overrange.over_range_mask` — the render must paint over-range pixels magenta too, so
  clips never show wrapped hot-spots as false cold (consistent with the live display).

## Backend

### Windowed, overlaid clip render
Extend the renderer (new `analysis/media.py` wrapping the shared frame compositor) to take:
- `start, stop, step` (frame window; the editor sets these), `scale` (1/2), `fps` and `speed`
  (output fps = source_fps × speed, or a fixed fps for GIF),
- `overlays`: `{ rois: bool, frame_stats: bool, timestamp: bool, colorbar: bool, title: str|None,
  plot: {roi_id, stat}|None }`,
- `format`: `"mp4" | "gif"`.

Frame composition (`thermal_frame_rgb` grows optional layers, each guarded by a flag): the existing
palette + colour bar + ROIs; a **frame min/max/mean** readout (from the header stats, over-range
excluded); a **title** caption bar; and the **animated live-plot inset** — a small axes in a corner
that draws the selected ROI's chosen stat (min/max/mean) from frame `start` up to the current frame,
with a moving playhead dot (data from `roi_series` over the window, precomputed once).

- **MP4:** the existing H.264 pipe at the window's fps×speed.
- **GIF:** two-pass ffmpeg — write frames to a temp, `palettegen` then `paletteuse` for clean
  colours; **size guard**: if `width·height·frames` exceeds a budget, auto-reduce fps (and warn in
  the job record) so a GIF can't balloon. Over-range pixels painted magenta as on screen.

Runs as a background job (reuse the pattern) under the run's `KeyedLocks`; `on_progress` drives the
editor's bar. Output: `exports/clips/<label>.mp4` / `.gif` (label from the title, slugified, or a
timestamp).

### ROI-stats plot + CSV for the window (companion)
`roi_stats_window(reader, rois, start, stop)` → a Matplotlib PNG plotting each ROI's **min/max/mean
vs time** over the window (mean line with a min–max band), plus `roi_stats_<in>-<out>.csv` (the
windowed `roi_series`) and a small summary (per ROI: mean, min, max, std, peak value & time).
Over-range pixels excluded (NaN) so the plot isn't poisoned. Written to `exports/`.

### API
- `POST /api/experiments/{name}/export/media` `{start, stop, step, scale, fps, speed, format,
  overlays, title, roi_source}` → starts the job, returns a job record; poll
  `…/export/media/status`. `roi_source` = `"stored" | "onscreen"` (stored default; on-screen posts
  the ROIs like the derived flow).
- `POST /api/experiments/{name}/export/roi-stats` `{start, stop}` → the plot/CSV/summary (may be a
  quick synchronous call or a small job).
- Served from the existing `exports/{file}` route.

## Frontend — full-screen editor

A modal overlay (`MediaExportEditor.tsx`) opened from a playback toolbar/rail button:
- **Preview:** the composed frame at the playhead (reuse the render path or compose client-side for
  responsiveness), reflecting every overlay toggle live (WYSIWYG).
- **Timeline:** the run's duration with **draggable in/out handles**, numeric in/out fields, and
  "set in/out at playhead"; a scrubber to preview any frame in the window.
- **Controls:** format (MP4/GIF), size (1×/2×), fps/speed; overlay toggles (ROIs+values, frame
  min/max/mean, timestamp, colour bar); a **title** text field; the **live-plot** picker (ROI +
  min/max/mean) and corner; ROI source (stored/on-screen).
- **Export** button → starts the job, shows a determinate **progress bar** (reuse `ProgressBar`),
  and on done links the file(s) in `exports/`. A separate **"ROI stats (plot + CSV)"** button runs
  the companion export for the same window.
- Layout must obey the app's existing patterns (no stretched button rows; wrap tidily).

## Brainstormed extras (v1 vs later)
v1: ROIs+values, frame min/max/mean, timestamp, colour bar, title, animated live-plot inset,
over-range magenta, GIF size guard. Later: peak-pixel crosshair+value, rate-of-change (°C/s),
run-name watermark / provenance footer (emissivity, range), absolute wall-clock timestamp.

## Test / verification plan
- Unit (TDD): window validation (`0<=start<stop<=n`, `step>=1`); GIF size-guard fps reduction;
  overlay flags produce the expected extra pixels (e.g., a title bar changes top rows; frame-stats
  text present); `roi_stats_window` CSV header + summary; over-range pixels magenta in a synthetic
  hot frame.
- Real-data: on a real run, export a 3-second MP4 and GIF with all overlays + a title and the
  live-plot inset; export the ROI-stats plot/CSV; confirm files land in `exports/`, play, and the
  numbers match `roi_series`. Verify a huge-window GIF triggers the size guard.
- Browser: the editor opens, in/out handles set the window, toggles change the preview, the
  progress bar runs, and the output links appear — verified against a real recording.

## Out of scope (deferred)
Recording-time media; multi-clip batch; audio; per-ROI colour editing in the editor (use the rail).
