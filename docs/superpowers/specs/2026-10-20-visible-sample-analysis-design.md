# Post-run visible-camera sample analysis

**Date:** 2026-10-20
**Status:** approved design (2026-10-20), ready for an implementation plan

## Why

On `20261020_144402_Run` the A70's visible camera (`visible.mp4`, RTSP `/avc/ch1`, 1280×960 H.264)
has the white PA12 powder clipped for the whole run. The camera's auto-exposure meters the dark cage
and metal and over-exposes the bright powder. Matt wanted the visible camera for two things: spotting
**sparks or arcs at the sample**, and watching the **doped part densify and slump** (it shrank 40–50 %
in Z under the powder surface).

Fixing exposure at the camera is not possible on firmware 4.45.003. It was checked on 2026-10-20,
reading only: GenICam has no visible-exposure node (all 249 device nodes, 2026-09-01 dump). ONVIF
imaging offers only Focus for both `video0` (IR) and `video1` (Visual). The web UI's JS (5 bundles,
including the service screen) has no exposure, brightness or backlight control. FLIR's internal
resource tree (`/prod/res/`, httpResource) has `.system.vcam` = {active, flash, fov, model `OV5640`,
test, torch} and no exposure entry. The sensor's exposure is set inside the camera's Linux, which is
reachable only through an unpublished SSH login (out of scope). Matt ruled out FLIR support and a
second camera.

What the clipped video still contains (measured on the run, 6,192 frames):

- The **powder** is unrecoverable. The right half sits at exactly 255; the left half is 245–254 with
  only a lighting gradient and compression blocks when contrast-stretched.
- The **sample** is well exposed (luma ≈ 110) and its outline changes over the run. Its dark area
  is steady at ≈1,040–1,090 px until ≈553 s, then falls to ≈700 px by 590 s, rises to ≈860 px near
  615 s, and ends near 630 px.
- **Visible events coincide with thermal events.** At ≈553 s the thermal sample max jumps ≈150 → 158 °C;
  at ≈615 s it jumps to ≈208 °C; at 627.77 s one frame shows a bluish-white glow on the lower half of
  the sample, just after the thermal max touched 250 °C (the top of measurement case 1).

So the useful output is: **the sample's visible area over time, flagged flash events at the sample,
and a contrast-stretched close-up of the sample**, all on the thermal time axis.

## Goals

1. After every recording that has a visible video, a visible-camera alignment and a sample ROI,
   automatically write:
   - `exports/visible_sample.csv`: one row per analysed visible frame (columns below);
   - `exports/visible_sample.json`: status, inputs, parameters, coverage and the list of flash events;
   - `exports/visible_sample_plot.png`: timeline with RF forward power, sample-ROI thermal max/mean,
     sample visible area, and the brightening metric with events marked;
   - `exports/visible_sample_closeup.mp4`: a crop around the sample with a fixed contrast stretch,
     at original timing (1×).
2. The same analysis on demand for existing runs, through the existing derived-files regenerate job.
3. Flash events appear in playback as timeline marks, reachable with the existing ◆◀ / ▶◆ buttons.
4. Add the 2026-10-20 exposure-control findings to `docs/visible_camera.md`, so nobody repeats the
   search.

## Non-goals

- Recovering powder detail, or any change to camera exposure.
- Detecting flashes away from the sample (cage, electrodes, cables). On this run the only off-sample
  whole-frame candidate (413.65 s) was a decoding glitch: a band of the image is shifted sideways.
- Live detection during a run.
- A visible-area trace inside the playback time plot (possible later; the PNG and CSV cover it now).
- Calling an event an "arc" or a "spark". The output says "flash at the sample". The video is
  ≈10 fps with gaps, and one frame cannot prove the cause.

## Anti-goals (a failure even if it runs)

- Writing to `thermal.zarr`, `visible.mp4`, `metadata.json` or any camera setting.
- **False green.** A run that could not be analysed must not look like "no events". "0 flashes" must
  always state how much of the run it covers.
- An analysis failure that blocks or delays Stop. It runs in the post-stop export job, where a
  failing step is logged and skipped (`api/app.py:436–455`).

## Inputs and their evidence

| Input | Where it comes from | Evidence |
|---|---|---|
| Visible segments and their thermal offset `t_start_s` | `visible.json` segments → `playback/visible_timing.thermal_segments` | Producer: `visible/recorder.py`. This run: one segment, `first_frame_host_ns` 1792521864065813000, so t_start = 25.996 s |
| Thermal frame 0 host time | `thermal.zarr/host_timestamp_ns[0]` | This run: 1792521838069768000 |
| Visible → IR homography | `metadata.json` → `visible_alignment.H` (normalised coordinates; keys H, note, pairs, rmsPx, saved_utc) | Consumer: `analysis/visible_overlay.py:35,94`. This run: `freehand_sample` maps to visible x 347–411, y 405–469; the dark sample measured at ≈(384, 430) |
| ROIs | `metadata.json` → `rois[]` = {id, kind, points/cx,cy,r, name} | This run: `powder` (circle), `freehand_sample` (polygon) and 5 others |
| Per-frame display times and keyframe flags | `ffprobe -show_entries packet=pts_time,flags` (`K` = keyframe) | 6,192 packets, 413 keyframes (median spacing 1.31 s). The stream is H.264 Baseline (no B-frames, `docs/visible_camera.md` "Measured streams"), so packet order is display order |
| Raw luma per frame | `ffmpeg -vf extractplanes=y -fps_mode passthrough -f rawvideo` | Passthrough gives exactly 6,192 frames. The default mode gives 6,193, inserting a duplicate that shifts all later times by one frame |
| RF forward power | `exports/control.csv` (`frame_id`, `forward_w`) | Producer: `api/app.py:187` |
| Thermal sample max/mean | `exports/roi_series.csv` (`t_s`, `frame_id`, `P{id}_max`, `P{id}_mean`) | Producer: `analysis/export.py:87` |

## How it works

### Which ROI is the sample

The sample ROI is the ROI whose name contains "sample" (case-insensitive). If there is more than one,
the smallest by area wins. *Builder's call, see "Calls I made".* With no match, the analysis does not
run and `visible_sample.json` says why. The bed ROI ("powder" or "bed" in the name) is optional; when
present it adds the `bed_clipped_frac` column.

### Geometry

Map the sample ROI's outline from IR pixels (640×480) into visible pixels (1280×960) through
`inv(H)`, using the same basis change as `ir_to_visible_coeffs`. Analysis region = the mapped polygon
grown by a margin (default 30 visible px). The margin absorbs alignment error (≈10 px on this run)
and lets the area grow.

### Per-frame metrics

For each visible frame (skip each segment's first `FRAME0_SKIP_S`):

- `t_s`: `t_start_s` of the segment + (pts − first pts);
- `frame`: index of the frame in its file; `segment`; `keyframe` (bool);
- `sample_dark_px`: pixels in the analysis region darker than the run's threshold;
- `sample_mean_luma`: mean luma of those pixels;
- `bed_clipped_frac`: fraction of the bed ROI (mapped) at 255, when a bed ROI exists;
- `brightening`: 99.5th percentile of (luma − previous frame's luma) over the analysis region.
  It is left empty on keyframes. On this run 85 of 93 large cup brightenings fell on keyframes,
  because the encoder's periodic refresh shifts brightness slightly.

**Threshold:** one value per run, chosen from the first 5 s of analysed frames (Otsu's method on the
analysis region), then held fixed. A fixed threshold keeps an exposure drift from masquerading as
area change. The chosen value goes into `visible_sample.json`. On this run Otsu gives 178 and a
start-of-run dark area of ≈1,096 px; the spike's fixed 170 gave ≈1,047 px.

### Flash events

A non-keyframe is **flagged** when

    brightening ≥ max(15, median + 6 × max(MAD, 1))

where median and MAD (scaled by 1.4826) are taken over the run's non-keyframe brightening values, in
luma levels. Flooring MAD at 1 avoids dividing by zero and keeps a near-silent run from flagging
noise. Flagged frames **within 1.0 s** of each other merge into one **event**: {t_start_s, t_peak_s,
t_end_s, peak_brightening, n_frames, peak frame index, bounding box of the brightened blocks}. The
peak is the flagged frame with the largest brightening. The effective threshold goes into the JSON.

Measured on this run with the design's region (mapped `freehand_sample` + 30 px, 13,543 px):
non-keyframe median 1.0 and MAD 1.48, so the 15-level floor binds. The rule gives exactly three
events:

| Event | Span (s) | Flagged frames | Peak |
|---|---|---|---|
| 1 | 553.95–554.06 | 2 | +20, frame 5303 |
| 2 | 615.66–615.85 | 2 | +19, frame 6005 |
| 3 | 627.77–629.41 | 7 | +97, frame 6142 |

Frame 6141 is +5 (not flagged); 6143 is +27 (flagged, inside event 3). Alternatives measured on the
same data: a 0.5 s merge splits event 3 (its last frame at 629.41 s is 0.517 s after the previous
one); a floor of 12 adds a one-frame event at 630.75 s (+12).

**Known margin:** the 413.65 s decoding glitch frame itself is +0.0 in this region on this run;
the +14 next to it is a keyframe at 413.84 s, which is excluded. Events 1 and 2 are only 4–5 levels
above the 15-level floor. With median 1.0, `median + 6 × MAD` exceeds the floor only when MAD > 2.33
(MAD 3 gives 19), so a noisier run raises the threshold and could drop events that size. That's why
the effective threshold is recorded with every result.

### Coverage (no false green)

`visible_sample.json` always carries:

- `status`: `ok` | `skipped` | `failed`, plus `reason` when not ok. Reasons include: no visible
  video, no alignment, no sample ROI, sample ROI maps outside the visible frame, ffmpeg missing.
- `frames_analysed`, the thermal time range covered, and `gaps_over_300ms` (62 on this run, from
  the camera throttling the stream while the radiometric stream runs).
- The inputs used: ROI id and name, `H` source, threshold, margin, z and luma limits, software
  version.

The playback marks and the export list read this file. A skipped or failed run shows its reason,
never an empty "no events".

### Close-up video

A crop around the analysis region (square, padded, even size). Luma is stretched linearly from the
run's sample luma (1st percentile) to 250 → 0–255, the same stretch for every frame. Scale ×3 with
Lanczos, original timing (every frame at its source time: `-fps_mode passthrough` on the source's
time base, no B-frames), H.264 CRF 20. Spike: a 200×200 crop at 3× gave a 4.6 MB
file at 10× speed.

### Plot

Four stacked panels on the thermal time axis: RF forward (W); sample ROI max and mean (°C), with
the case ceiling drawn when the max reaches it; `sample_dark_px` (raw, plus a 31-frame rolling
median); `brightening` with events marked. This matches the spike figure. Draw it with Pillow, the
way `analysis/run_summary.py` draws `roi_plot.png` ("Pillow only (no matplotlib dependency on the
operator)", `run_summary.py:6`); no new dependency.

### Where it runs

- **Post-stop:** a new step "visible sample analysis" in `_schedule_post_stop_exports`, after "run
  summary" and before "thermal preview video render" (`api/app.py:445`). The spike took 20 s for
  607 s of video on this Mac.
- **On demand:** a new step in the `/export/derived` job (`api/app.py:1571`), because the result
  depends on the ROIs. Its progress shows in the existing job record.
- **Playback marks:** `GET /api/experiments/{name}` exposes the events (and status) from
  `visible_sample.json`. `eventsToMarkers` (`frontend/src/lib/events.ts`) adds them as a "visible
  flash" marker type with its own colour. They are not written into `events.json`, which stays the
  recorder's record.

### New code

- `backend/flir_research_interface/analysis/visible_sample.py` holds the pure functions: ROI mapping,
  threshold, per-frame metrics on a luma array, z-scoring, event merging, coverage summary. A thin
  runner does the ffprobe/ffmpeg I/O and writes the four files.
- Frontend: marker type and colour; show the status and reason next to the export files.

## Testing (TDD, real-data fixtures)

Red-green per pure function. Fixtures are **captured from `20261020_144402_Run`**, never invented:

- the luma crops (analysis region) of frames 6141, 6142, 6143 (before, glow, after) as `.npy`, and
  one frame at 300 s;
- `visible_alignment` and `rois` from its `metadata.json`;
- the packet table (pts, flags) for the frames around 627.8 s;
- a short brightening series around 553–630 s from the real run, for event merging.

Expected values come from this design's measurements: `freehand_sample` maps to x 347–411,
y 405–469; frame 6141 is not flagged, 6142 is flagged and is event 3's peak, 6143 is flagged inside
event 3; keyframes never produce events; the event table above is the expected output for the run.

Before shipping: one end-to-end run on the real `20261020_144402_Run`. Print the JSON and check:
exactly the three events in the table; nothing at 413.65 s; threshold 178 and a start-of-run dark
area near 1,096 px; coverage fields filled. Also check that a run without
visible video and a run without a sample ROI both produce `status: skipped` with a reason.

## Calls I made (check these)

- Sample ROI chosen by name ("sample"), smallest wins; no new UI to pick it.
- Close-up at 1× timing rather than sped up, so it lines up with the thermal playback.
- Flash rule ≥ max(15, median + 6 × max(MAD, 1)) luma levels, merged within 1.0 s, sample region
  only. The builder check showed the first draft's rule (z ≥ 10, 0.5 s) could not produce the
  promised results; this one was chosen from measurements on the run.
- Events shown as playback marks only; no new trace in the time plot.
- Threshold by Otsu on the first 5 s, fixed per run.

## Left to the builder

File layout inside the module, chunked decoding, exact plot styling, the marker colour, test file
names, and how the runner is wired into the two existing job paths.
