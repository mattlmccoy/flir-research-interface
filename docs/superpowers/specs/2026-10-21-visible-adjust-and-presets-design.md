# Visible-video adjustments and camera presets

**Date:** 2026-10-21
**Status:** approved design (2026-10-21), ready for an implementation plan

## Why

The A70's visible video over-exposes the white powder (see `docs/visible_camera.md`, 2026-10-20
section). The camera exposes no exposure control to software, so Matt wants to adjust the video
**ourselves**: exposure, brightness and contrast on the **recorded** video when reviewing a run, and
the same sliders on the **live** visible preview before recording. The raw video must stay exactly
what the camera sent; the settings are remembered with each run. The post-run visible-sample analysis
(spec `2026-10-20-visible-sample-analysis-design.md`) can optionally run on the adjusted video.

Matt also wants **presets** that survive app restarts, so a lab setup is one click: the visible
sliders, the thermal camera settings, and the thermal display settings.

Software cannot recover pixels the camera stored as 255: the clipped part of the powder stays flat.
Near-white, mid and dark areas (the sample, the cage, the electrodes) become easier to see.

## Goals

1. **One adjustment model** (exposure, brightness, contrast) used identically in the browser and in
   Python.
2. **Live:** sliders in the visible-camera panel change the live preview immediately, in every
   visible view mode (rail, side by side, overlay, pop-out).
3. **Recording:** when recording starts, the current adjustment (and preset name, if any) is stored
   in the run's `metadata.json`. `visible.mp4` stays a stream copy.
4. **Playback:** the visible video shows the run's adjustment; the sliders change it; changes are
   saved with the run in a sidecar; "reset to as-recorded" restores the recorded values.
5. **Media export** clips that include the visible video use the run's current adjustment.
6. **Analysis option:** a checkbox in the Export section runs the visible-sample analysis on the
   adjusted video; the default stays raw; the result records which adjustment was used.
7. **Presets:** named presets stored on the operator, holding visible adjustment + thermal camera
   settings + thermal display settings; save, apply, rename, delete; the last applied preset is
   remembered across restarts.
8. `docs/visible_camera.md` describes the adjustments and presets.

## Non-goals

- Changing the camera's own exposure (not possible; see the 2026-10-20 findings).
- Burning adjustments into any recorded file.
- Gamma curves, white balance, per-region adjustments, auto-levels (possible later).
- Presets for ROIs, masks or the metadata profile (the profile already persists, `analysis/profile.py`).

## Anti-goals (a failure even if it works)

- Any change to `visible.mp4`, `thermal.zarr` or the radiometric numbers.
- The analysis silently using adjusted video: it must be an explicit choice, recorded in its JSON.
- Writing thermal camera settings without the operator's action: never at app start, never while a
  recording runs, never a node outside the app's writable list.
- A preset edit or delete changing how an old run is described (runs store values, not references).

## Inputs and their evidence

| Fact the design relies on | Evidence |
|---|---|
| The visible recorder stores the RTSP stream without re-encoding | `visible/recorder.py:4` ("No re-encode (`-c copy`)") |
| `Recorder.start` can add top-level blocks to `metadata.json` | `recording/recorder.py:268` ("`extra` adds top-level blocks … e.g. `visible_alignment`") |
| Recording start request carries `rois`, `masks`, … | `api/app.py:106-116` (`RecordingStartRequest`) |
| Per-run sidecars live in the run folder, atomic, tolerant, travel with offload | `labels.py:1-9` (`labels.json`) |
| Operator-side settings shared by every browser | `analysis/profile.py:1-7`, `calibration/profile.json`, `GET/PUT /api/profile` (`api/app.py:787,793`) |
| Writable thermal nodes and their ranges | `camera/controls.py:13-28`: `ObjectEmissivity` 0–1, `ReflectedTemperature`, `AtmosphericTemperature`, `ExtOpticsTemperature` 0–5000 K, `ObjectDistance` 0–10000 m, `RelativeHumidity` 0–1, `ExtOpticsTransmission` 0–1, `CurrentCase` (int), `NUCMode`, `IRFrameRate` (enums from the camera) |
| Writing them: `POST /api/camera/parameters`, refused (409) while recording | `api/app.py:726` |
| Current values: `GET /api/camera/info` → `object_parameters`, `active_case.index`, `nuc_mode`, `nodes.IRFrameRate`, `enum_options` | `camera/spinnaker.py:157-166`; real response captured 2026-10-20 (emissivity 0.95, distance 0.457 m, case 1, NUC Automatic, Rate30Hz) |
| Layout/view state (visible mode, overlay opacity, AGC, filters) persists in browser storage | `frontend/src/lib/layout.ts:227,272` (`loadLayout` / `saveLayout`) |
| Palette is App state, not persisted today | `frontend/src/App.tsx:174` |
| Live visible preview is an `<img>` (MJPEG); playback visible is a `<video>` of `visible.mp4` | `frontend/src/components/VisiblePanel.tsx:33,36,92,96` |
| Media export blends the visible frame over IR in Python | `analysis/visible_overlay.py` (`blend_visible`) |
| Visible analysis decodes luma and encodes the close-up with ffmpeg `lutyuv` | `analysis/visible_sample_run.py`, `analysis/visible_sample_io.py` |
| The camera encodes **full-range** luma but does not tag it | Measured on `20261020_144402_Run/visible.mp4` (13 frames sampled): Y spans 0–255, 1.5 % of pixels at 236–254, 0.8 % at 255; ffprobe `color_range=unknown` |
| A lossless re-wrap can tag it | `ffmpeg -c copy -bsf:v h264_metadata=video_full_range_flag=1` on a 2 s clip gives `color_range=pc` (ffmpeg 6.1, 2026-10-21) |
| Offload treats only some run files as editable | `storage.py:43` (`MUTABLE_PATHS`: `labels.json`, `exports/*`) |
| Run routes take a `library` (local or drive) | `labels` routes use `_exp_dir_in` (`api/app.py`) |
| Simulated and Spinnaker `camera_info` differ | Spinnaker: `nodes.IRFrameRate`; simulated: top-level `ir_frame_rate`; both have `enum_options`; `object_parameters` also holds non-writable `EstimatedTransmission`, `UseWindowTemperature`, and values can be `None` |
| Changing the measurement case triggers a NUC and range switch; `set_parameters` writes in order without rollback | `docs/radiometry.md` §4; `camera/spinnaker.py` `set_parameters` |

## Full-range display (found while checking this design)

Browsers and ffmpeg's default conversion read an untagged stream as TV range (16–235), so today the
app shows every pixel from 235 up as white: the near-white powder detail (1.5 % of the frame on the
reference run) is lost **before** any adjustment. The analysis already reads raw Y (0–255). Fix the
display paths so all three agree, without touching the recorded file:
- **Playback:** the visible `<video>` plays a full-range-tagged copy, made once by a lossless re-wrap
  (`-c copy -bsf:v h264_metadata=video_full_range_flag=1`) into `exports/visible_full_range.mp4`
  (`_001` etc. per segment), built on first request and served with HTTP range support. `visible.mp4`
  is never modified. Cost: a second copy of the same size (77 MB on the reference run), regenerable.
- **Live preview:** the MJPEG transcode (`visible/preview.py` `mjpeg_command`) reads the input as full
  range (`scale=…:in_range=full:out_range=full`).
- **Media export:** the visible frame extraction in `analysis/visible_overlay.py` reads full range too.
- A browser gate confirms it: draw a playback frame to a canvas and read back two pixels whose raw Y
  are 245 and 255; they must differ.

## The adjustment model

Settings: `exposure_ev` (−3 … +3, default 0), `brightness` (−0.5 … +0.5, default 0),
`contrast` (0.25 … 4, default 1). For a pixel value `x` in [0, 1]:

    g = 2 ** exposure_ev
    y = clip(contrast * (g * x - 0.5) + 0.5 + brightness, 0, 1)

This is one linear map, `y = clip(slope * x + intercept)`, with `slope = contrast * g` and
`intercept = 0.5 - 0.5 * contrast + brightness`. It is applied to R, G and B alike. Because luma is a
weighted sum of R, G, B with weights summing to 1, the same map applies to luma (Y) for the analysis
(clipping per channel can differ only where a channel saturates; the analysis uses the Y form).

- Browser: an SVG `feComponentTransfer` filter with `type="linear"` slope/intercept on R, G, B and
  `color-interpolation-filters="sRGB"`, referenced by CSS `filter: url(#…)` on the `<img>`/`<video>`.
  CSS `brightness()`/`contrast()` are not used: they cannot express the offset exactly and would not
  match Python.
- Python: a pure function `adjust_linear(settings) -> (slope, intercept)` and an applier on uint8
  arrays (luma or RGB), rounding to nearest.
- A **parity test** runs the same table of settings through the TS and Python functions and requires
  identical slope/intercept, and identical uint8 output on a captured luma crop (fixture from
  `20261020_144402_Run`).

## Live

- Sliders (exposure, brightness, contrast) and "reset" in the visible-camera rail section, next to the
  existing opacity slider; they apply to every visible view (rail, side, overlay, pop-out).
- The current live adjustment persists in the browser like the other view settings (`layout.ts`), and
  is also the "current" adjustment a preset save captures. At page load the browser-stored current
  adjustment wins; only a browser with nothing stored starts from the `last_applied` preset.
- The preset dropdown shows `last_applied`, marked "(modified)" when the current values differ from
  it.

## Recording

- `RecordingStartRequest` gains `visible_adjust: {exposure_ev, brightness, contrast, preset: str|null,
  based_on: str|null}` (validated ranges). `preset` is the last-applied name only when the visible
  values equal that preset's; when they differ, `preset` is null and `based_on` holds the name. The backend passes it to `Recorder.start(extra={"visible_adjust": …})`, so it is
  stored top-level in `metadata.json` next to `visible_alignment`. Arming (triggered start) carries it
  automatically: `ArmRequest` extends `RecordingStartRequest` (`api/app.py:126`).
- Nothing about the visible recording command changes.

## Playback

- The adjustment shown is, in order: the run's sidecar `visible_adjust.json` if present, else
  `metadata.visible_adjust`, else neutral (runs recorded before this feature).
- Moving a slider saves the sidecar (debounced) via `PUT /api/experiments/{name}/visible-adjust`;
  "reset to as-recorded" deletes the sidecar (`DELETE`, same route). Sidecar writes follow
  `labels.py` (atomic temp + replace, tolerant reads). `GET /api/experiments/{name}` returns
  `visible_adjust` (effective) and `visible_adjust_recorded` (from metadata) so the UI can show both.
- The sidecar is ordinary run data: offload copies it with the run. Add `visible_adjust.json` to
  `storage.MUTABLE_PATHS` (like `labels.json`), and give the routes the same `library` argument as the
  labels routes.
- **Presets in playback:** the dropdown offers "apply look": it writes the preset's visible part into
  this run's sidecar and applies its display part to the view. It never writes camera settings, and
  playback has no "save preset".

## Media export

- When a clip includes the visible video (overlay or side by side), the warped visible frames get the
  run's effective adjustment in Python before blending (`visible_overlay.py`). The export request does
  not need a new field: the backend reads the run's effective adjustment.

## Analysis on the adjusted video

- The Export section gains a checkbox "analyse with the display adjustment" next to the visible-sample
  line (default off). It is sent to the derived job (`/export/derived?visible_adjusted=true`).
- `analyse_visible_sample(reader, …, adjust: dict | None = None)`: when given, the decoded luma is
  mapped with `adjust_linear` before the threshold, `sample_dark_px`, `sample_mean_luma`, brightening
  and the close-up (whose `lutyuv` composes the adjustment and the existing stretch).
  `bed_clipped_frac` always uses **raw** luma: it reports what the camera clipped, which an exposure
  cut would otherwise hide.
- **Separate result:** the adjusted analysis writes its own files, `exports/visible_sample_adjusted.{csv,json,png}`
  and `visible_sample_adjusted_closeup.mp4`, so it never overwrites the raw result and no regenerate
  that lacks the flag can erase it. The raw result stays the default and drives the playback flash
  marks. The Export section shows a second status line for the adjusted result.
- The adjusted summary gains `adjust: {exposure_ev, brightness, contrast, source}` (`source`:
  `"sidecar"` or `"recorded"`). Its status line says "(adjusted: exposure … brightness … contrast …)".
  When the run's current adjustment differs from the one it used, it adds "; sliders changed since"
  so a stale result never reads as current.
- The checkbox state is remembered in the browser; the regenerate buttons re-run the adjusted analysis
  only when it is ticked.
- The flash rule is unchanged (15-level floor in the analysed luma), so results on adjusted video can
  differ from raw; a strong exposure boost can clip a flash. The docs say so.
- The post-stop automatic analysis stays raw.

## Presets

Stored on the operator at `<experiments_root>/calibration/presets.json` (atomic write, tolerant read,
same pattern as `profile.json`):

    {"version": 1, "last_applied": "sintering bed" | null,
     "presets": [{"name": "sintering bed",
                  "visible_adjust": {"exposure_ev": -1.0, "brightness": 0.0, "contrast": 1.4},
                  "thermal": {"ObjectEmissivity": 0.95, "ObjectDistance": 0.457,
                              "ReflectedTemperature": 293.15, …, "CurrentCase": 1,
                              "NUCMode": "Automatic", "IRFrameRate": "Rate30Hz"},
                  "display": {"palette": "iron", "range": {"mode": "auto"} |
                                                          {"mode": "locked", "min_c": 20, "max_c": 250}},
                  "saved_utc": "…"}]}

- Thermal values use the camera's own units (K, m, fractions), exactly the `WRITABLE_NODES`; the UI
  shows °C where it already does. Any other key is rejected on save.
- API: `GET /api/presets`, `PUT /api/presets/{name}` (create or replace), `DELETE /api/presets/{name}`,
  `POST /api/presets/{name}/rename`, `POST /api/presets/last-applied`. Validation uses
  `camera/controls.py` ranges; enum values must be in the camera's current `enum_options` when a
  camera is connected (otherwise stored as given and validated at apply time).
- **Save current as…** (in the visible-camera section and the camera-settings section): reads the
  live camera values from `GET /api/camera/info`, the current sliders and the current palette/range.
  Requires a connected camera for the thermal part; without one, the thermal block is omitted and the
  dialog says so.
- **Apply:** sets the sliders and the display at once; writes the thermal block through the existing
  `POST /api/camera/parameters` and reports which values changed. `CurrentCase` is written last and
  the confirmation warns that changing the measurement case triggers a NUC and a range switch. The
  write is not atomic, so a failure part-way reports which values were applied and which were not.
  Blocked while recording (the endpoint returns 409; the UI shows that and applies only the visible +
  display parts, saying so). Records `last_applied`.
- **Save current** reads only the writable nodes, from either backend's `camera_info` (Spinnaker
  `nodes.IRFrameRate`, simulated `ir_frame_rate`; `object_parameters` minus `EstimatedTransmission` and
  `UseWindowTemperature`); a `None` value is left out of the preset, and the dialog says which.
- Rename updates `last_applied` if it pointed at the old name; delete clears it.
- **Startup:** the preset dropdown shows `last_applied`. The browser's stored current settings win;
  a browser with nothing stored starts from `last_applied`'s visible and display parts. The thermal
  part is **not** written until the operator clicks "apply camera settings" (a visible prompt).
- A recording started with a preset stores the full values (Recording section) plus the preset name.

## Testing

Red-green throughout. Captured fixtures, never invented:
- the parity table (TS ⇄ Python) and a luma crop from `backend/tests/fixtures/visible_sample_20261020_144402.npz`;
- a real `GET /api/camera/info` object captured from the A70 for preset "save current" (store it as a
  fixture when the camera is next connected; until then the test uses the 2026-10-20 values quoted in
  this spec and says it is shape-only).

Real-data and hardware gates:
- Playback on `20261020_144402_Run` in the browser (sliders change the visible view; sidecar written;
  reset restores; media export clip shows the adjustment; the full-range pixel check above).
- The adjusted analysis on that run with a stated adjustment, compared with the raw result.
- Live preview, recording stamp and preset apply need the camera: run them when the rig is available;
  until then they are marked untested on hardware in the docs.

## Calls I made (check these)

- Controls and ranges: exposure ±3 EV (×1/8 … ×8), brightness ±0.5 of full scale, contrast 0.25–4.
- One linear model for all three, applied by an SVG filter in the browser (exact parity with Python).
- Review edits go to a sidecar `visible_adjust.json`; `metadata.json` keeps the as-recorded values.
- Analysis default stays raw; the automatic post-stop analysis stays raw.
- Presets include palette and display range; thermal values are stored in the camera's units.
- Thermal settings are never re-sent at startup without the operator's click.
- Display paths read the video as full range, via a regenerable re-wrapped copy for playback
  (`exports/visible_full_range.mp4`, the same size as `visible.mp4`).
- Playback offers "apply look" only (visible + display into this run), never camera settings, never
  save.
- The browser's stored sliders win over `last_applied` at reload; recordings stamp `preset` only when
  the values match, otherwise `based_on`.
- The adjusted analysis gets its own files; the raw result drives the timeline marks;
  `bed_clipped_frac` stays raw.

## Left to the builder

Slider styling and debounce interval, file layout within the modules, the dialog wording for save and
apply, and the exact placement of the preset dropdown.
