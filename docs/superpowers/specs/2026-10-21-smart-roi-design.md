# Smart ROI: a tracked, contour-following ROI with offset rings and dimensions

Date: 2026-10-21. Status: design agreed in conversation with Matt; builder review done (2026-10-21);
awaiting Matt's final read. Mockup of the intended behaviour (simulated data, the proposed edge rule):
`smart_roi_mockup.png` (sent in the session; three moments: searching → locked → expanded).

## 1. Intent and why

Matt heats irregular graphite samples with RF inside a Faraday cage and images them with the FLIR
A70. Today he measures them with a rectangle (or other fixed-geometry) ROI. A rectangle never matches
an irregular sample: it mixes cooler background into the statistics, pulling the mean down and
blurring the peak, and the sample **expands as it heats**, so a fixed shape drifts further off as the
run goes on.

The smart ROI fixes that: Matt draws a rough outline around the sample; each frame the tool finds the
sample's real outline from the thermal image and measures exactly those pixels, following the sample
as it grows. Around that outline it measures **offset rings** to show how heat spreads into the
surrounding powder, and it reports the sample's **in-situ dimensions** over the run, which Matt wants to
compare against the CAD geometry.

Success: on a real graphite run, the smart ROI's outline visibly hugs the sample from the moment it
stands out to the end of heating, its statistics and the ring statistics are plotted and exported
like any other ROI, and its size-over-time trace is believable next to calipers before/after.

## 2. Goals, non-goals, anti-goals

**Goals (v1)**
- New ROI kind (working name `smart`): user draws a rough outline (the *search area*, a polygon or
  freehand shape, reusing the existing drawing tools).
- Per frame, find the sample inside the search area and use its outline as the measured region.
- Track: re-find every frame so expansion / small movement is followed.
- Offset rings around the tracked outline, set in **pixels** per smart ROI (default 5, 10, 25 px),
  each measured as its own band.
- Dimensions per frame: area, length and width along the sample's own long/short axes, % change
  since the outline first locked, perimeter, centroid, and an edge-sharpness figure.
- Works everywhere an ROI works today: live view overlay and readout, the live feed TC-POWER reads,
  playback plot / series, exported files, and saved with the recording.
- Two edge rules: **relative** (default) and **fixed temperature** (user picks the °C that defines
  the edge) — see §4.

**Non-goals (v1)** — explicitly later:
- Real millimetres. Everything is in pixels. A pixel→mm scale (first a manual "draw a line of known
  length", later an in-frame dielectric calibration target Matt is designing) is a separate project.
  The design must leave a clean place for it (§6) but must not build it.
- CAD overlay / automatic comparison to CAD geometry.
- Multiple disjoint samples inside one smart ROI (one smart ROI = one sample; draw two ROIs for two).
- Samples that are *colder* than their surroundings.

**Anti-goals** (would make this a failure even if it technically works)
- Reporting a plausible number when the sample has not been found. Before lock, and on a frame where
  detection fails, the smart ROI must read as not-valid / not-locked — never as a healthy value
  (house rule: unknown must never render as healthy; the live feed's existing `valid:false` contract
  in `analysis/live_temps.py` applies).
- The outline jumping to noise, to an electrode, or to a neighbouring hot part between frames.
- The live view or recording dropping frames because detection is too slow (camera runs 30 fps).
- A malformed or half-drawn smart ROI breaking the live feed for all ROIs (we just fixed exactly this
  for rectangles: commit d7558a6 — one bad ROI must only invalidate itself).
- Presenting the thermal outline as the physical outline without saying so (§5).

## 3. What Matt sees (behaviour)

1. He picks the smart-ROI tool and draws a loose outline around the sample (white dashed in the
   mockup). Status: **"searching… (not locked yet)"**, no temperatures shown.
2. When the sample stands out, the tool locks: a solid outline (the tracked edge) and dashed rings
   appear; the readout shows the sample's mean/max/min, each ring's mean/max/min, and the dimensions.
3. As the sample expands, outline and rings move with it each frame; nothing is redrawn by hand.
4. If a frame fails (see §4), the last good outline is held and the ROI is flagged
   (**"holding — edge lost"**); it does not jump. If failure persists past a short timeout it returns
   to "searching" and reports not-valid.
5. In playback the same outline and rings are drawn for every frame, and the plot offers the sample,
   each ring, and the dimension traces.
6. ROI settings for a smart ROI: ring offsets (px), edge rule (relative / fixed °C + value),
   sensitivity (see §4), name/colour like other ROIs.

Matt confirmed: the graphite **stays the hottest thing in the search area for the whole run**; the
surrounding powder warms later. The sample **expands a bit** while heating, so tracking is required.

## 4. Finding the edge

**Relative rule (default).** Within the search area, estimate the sample's hot level and the
surroundings' level from that frame (the mockup used the 99th and 20th percentiles of the search
area) and place the edge where temperature crosses halfway between them. Keep the largest connected
region above that level, fill its holes. Because both levels are re-estimated each frame, the rule
adapts as the powder warms. The halfway point is the default; a **sensitivity** control moves it
(e.g. 30–70 % of the way from surroundings to core). Exact estimators are the builder's choice as long
as they are robust to noise and to over-range pixels.

*Decision (Matt, 2026-10-21):* the hot level is the **90th percentile of the chosen region** (not
p99/peak), so a few smoking or arcing pixels far hotter than the sample never set the edge. The
reported `max_c` is unchanged, so those hot spots stay visible in the readout.

**Fixed-temperature rule.** The edge is the user-chosen °C isotherm. Behaves more like a physical
boundary once the whole sample is above that temperature; used when comparing dimensions to CAD.

**Lock / hold / search states.**
- *Searching*: no region passes the sanity checks (e.g. not enough contrast between core and
  surroundings, or the region is tiny). Not valid.
- *Locked*: a region found and consistent with the previous frame.
- *Holding*: this frame's result failed a consistency check (sudden large jump in area or centroid,
  region touching the search-area border, contrast collapsed) — use the last good outline, flag it.
  The thresholds for "sudden" are the builder's call, but must tolerate the sample's real expansion.
- The search area **grows with the tracked outline** (keeps a margin around it) so expansion can
  never push the sample out of it. The user's drawn outline is the starting search area.

**Over-range pixels** (saturated / wrapped, already detected by `lib/overrange.ts` in the browser and
`over_range_mask` on the operator) are excluded from the edge estimate; the existing rule that an ROI
containing over-range pixels reports invalid stays.

## 5. Dimensions and the thermal-edge caveat

Reported per frame, in pixels: area; length and width along the region's principal (long/short)
axes; % change of each since first lock; perimeter; centroid (x, y); **edge sharpness** (how steep the
temperature step is across the outline, e.g. mean gradient magnitude on the boundary).

The outline is a **thermal** edge. It moves when the sample physically grows, but also when heat
spreading blurs the boundary. The UI and exports must label the dimensions as measured from the
thermal edge, and show edge sharpness alongside so a size change that coincides with blurring is
visible. The fixed-temperature rule is the recommended mode for CAD comparison. Matt can validate
against caliper measurements before/after a run.

## 6. Where it plugs into the existing code (constraints found in the repo)

Evidence from the code as of commit `356ab71`:
- ROI kinds are fixed geometry: `frontend/src/lib/roi.ts:23-35` (spot, rect, circle, ellipse, line,
  polygon, polyline); backend `analysis/series.py:32 parse_rois` and `:232 roi_index(roi, w, h)`.
  **Every consumer assumes an ROI's pixels depend only on its geometry**: `roi_index` takes no frame,
  and results are cached per ROI (`recording/arm.py:127-136 _roi_index` cache; series caches in
  `analysis/series.py`). A smart ROI's pixels depend on each frame's content, so this assumption has
  to be relaxed for the new kind without slowing the existing kinds.
- Consumers that measure ROIs and must handle the new kind: live view (browser,
  `lib/roi.ts:376 roiStats`, called from `components/ThermalView.tsx:230`); live feed for TC-POWER
  (`analysis/live_temps.py`, via `roi_index`, `GET /api/live/roi-temps`); playback series
  (`analysis/series.py:394 roi_series`, `api/app.py` ~1782-1797); exported CSV/plots
  (`analysis/export.py:89`, `run_summary.py:224`, `media.py:263`, `annotate.py:273`); armed-recording
  trigger (`recording/arm.py`).
- ROIs are measured in **two places**: the browser (live view readout) and the operator (everything
  else). **My call:** the operator is the single source of truth for the smart ROI's outline and
  numbers; the browser draws the outline it receives (live: alongside each frame message,
  `api/frames.py:83 encode_frame_message` already carries `extra`; playback: per frame) rather than
  re-implementing detection in TypeScript. This avoids two detectors drifting apart. If the builder
  finds a strong reason to also detect in the browser, parity tests against shared fixtures are
  required.
- Not to be confused with the existing **region masks** (`lib/mask.ts`): include/exclude shapes that
  only steer colour auto-range and frame stats, with no readout or series. The smart ROI is an ROI.
- Ring/dimension outputs are new series per smart ROI (sample + one per ring + dimension traces);
  naming in CSV/plots is the builder's call but must make the band explicit (e.g. `graphite ring
  5–10 px mean`).
- **Units hook for later mm:** dimensions and ring offsets are stored in pixels with a units field so
  a future scale can convert them; nothing in v1 depends on a scale existing.
- Recording: the smart ROI definition (search outline, ring offsets, edge rule) is saved with the
  run like other ROIs, and per-frame results (state, dimensions, ring stats) are recoverable for the
  whole run — either stored at record time or recomputable from the stored frames; the builder picks,
  but playback of a finished run must not depend on the live session.

## 7. Constraints

- Camera: A70, 640×480, 30 fps, radiometric (TemperatureLinear counts). Detection must keep up with
  live display/recording at 30 fps or degrade gracefully (e.g. re-detect at a lower rate and reuse
  the last outline in between), never by dropping camera frames.
- Playback series over long runs (tens of thousands of frames) must stay usable; the existing
  strided/cached series path is the model.
- Strict mypy + ruff + pytest backend; `node --test` + `tsc` frontend; CI runs all of them.
- House rules: red-green TDD; test fixtures **captured from real data** (a real graphite run), not
  invented — synthetic frames are fine for unit tests of the geometry but acceptance must run on a
  real recording; one real-data end-to-end check before shipping.
- Never restart the lab operator without Matt's go-ahead.

## 7a. Decisions made during review (my calls — Matt to check)

These came out of a builder review of this document; each is the designer's call, not something Matt
stated, and is listed so he can overrule it.

- **Playback, export and live agree frame for frame.** Tracking carries state between frames (hold,
  growing search area), so a strided recompute would disagree with what the live feed showed. Smart
  ROI results are computed **once at full rate** and stored with the run (during recording; for a
  smart ROI added to a finished run, by a full-rate background job with progress, like the existing
  derived-export jobs). Playback and export read the stored results; the strided series path is not
  used for smart ROIs.
- **Live feed shape (`GET /api/live/roi-temps`).** The smart ROI keeps one entry with the same flat
  fields as today (id, name, kind, mean/max/min, valid). Rings and dimensions are **added inside that
  entry** as new keys (`rings: [...]`, `dims: {...}`, `state: searching|locked|holding`) so the roster
  TC-POWER keys on does not change. Before relying on rings in TC-POWER, confirm with the TC-POWER
  session that extra keys are tolerated (FLIR's own intake ignores unknown keys; TC-POWER's parser is
  not in this repo).
- **Emissivity.** The sample uses the ROI's emissivity as today. Rings measure powder, so a smart ROI
  gets **one optional ring emissivity** (defaulting to the sample's), shown in the settings and
  recorded in exports. The fixed-temperature edge rule compares against the **sample's** corrected °C.
- **Armed-recording trigger.** v1 does **not** allow a smart ROI as the trigger ROI (the trigger
  fires while the sample is still cold, i.e. before lock, and the trigger runs on the camera thread's
  tightest budget). Triggers keep using fixed-geometry ROIs; the UI disables the smart ROI there.
- **Baseline and re-lock.** "% change" is relative to the **first lock in the recording** and keeps
  that baseline through hold/search/re-lock (the expansion trace must not silently reset). After a
  fall-back to searching, the search area is the last grown search area **capped** at the user's
  drawn outline plus a margin, so it can never wander onto an electrode far from where Matt drew.
  Pre-trigger frames count as part of the recording.

## 7b. Decided by Matt during review

- **Holding → feed stays valid (option A).** While the smart ROI holds its last good outline after a
  failed frame, `GET /api/live/roi-temps` keeps reporting the held outline's temperatures as
  `valid: true` with `state: "holding"`, so a single noisy frame does not pause heating. Only when the
  hold outlasts the hold window (builder's default, short — on the order of a second) does it go to
  `searching` and `valid: false`. Matt chose this conditional on the acceptance fixture below being the
  best available run; it is (checked 2026-10-21, see below).
- **Acceptance fixture: `20261020_144402_Run`** (FLIR SSD, `FLIR-recordings/`). Graphite/PA12 doped
  1-inch cube in natural PA12 powder, power steps 5–300 W, 631 s, 18,951 frames, TemperatureLinear10mK,
  complete. It already contains a hand-drawn `freehand_sample` polygon ROI around the cube — use it as
  the search outline. Measured with the proposed relative rule (no connected-component step):
  - contrast core(p99) − surroundings(p20) is 0.2 °C at t = 0, ~4 °C by 55 s, 44 °C at 274 s,
    ~90 °C at 604 s → exercises searching → lock from cold;
  - thresholded area ~820–910 px through heating, then ~765 (549 s) → 607 px (604 s), matching Matt's
    note that the cube collapsed at 553.7 s → exercises tracking through a real shape change;
  - it shows **no clear expansion** (area creeps down slightly as the powder warms — the thermal-edge
    effect of §5). A second fixture with visible growth is wanted later; not a blocker.
  - Matt's notes cite `SWEEP_NOTES.md` for this run; no caliper before/after is recorded here.

## 7c. Dependency gap found

The operator's Python environment has **no `scipy`** (checked 2026-10-21), and the connected-region /
hole-fill / distance-transform steps need it or an equivalent. Adding a dependency to `backend/` must
use `uv add` + `uv sync --extra dev --inexact` — never a bare `uv sync`, which strips the manually
installed PySpin wheel. Implementing the few operations in numpy instead is an acceptable alternative;
builder's call.

## 8. Left to the builder

Exact estimators and default thresholds for the edge, sensitivity range, consistency checks and
timeouts; how per-frame outlines are encoded and sent; whether results are stored at record time or
recomputed; CSV/plot naming; UI layout of the smart-ROI settings; performance strategy.

## 9. Later (separate projects, not in this build)

- Pixel→mm scale: manual two-point line first, then the in-frame dielectric calibration target
  (reference must sit at the sample's focal plane; contrast needs a temperature difference to its
  reflected surroundings).
- CAD comparison/overlay once mm exists.
