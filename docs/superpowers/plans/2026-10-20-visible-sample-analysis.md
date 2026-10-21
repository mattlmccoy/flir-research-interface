# Post-run visible sample analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each run (and on demand for old runs), analyse `visible.mp4` around the sample and write `exports/visible_sample.{csv,json,png}` plus a contrast-stretched close-up MP4, with flash events shown as playback marks.

**Architecture:** Pure numpy functions in `analysis/visible_sample.py` (ROI mapping, threshold, per-frame metrics, flash events, coverage), an I/O runner in `analysis/visible_sample_run.py` (ffprobe/ffmpeg, segments, file writing), and a Pillow plot in `analysis/visible_sample_plot.py`. The runner joins the existing post-stop export chain and the `/export/derived` job. The frontend reads the summary from `GET /api/experiments/{name}` and adds marks.

**Tech Stack:** Python 3.12, numpy, Pillow, zarr, FastAPI, ffmpeg@6/ffprobe; React + TypeScript, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-20-visible-sample-analysis-design.md` (approved 2026-10-20). Read it first; it carries the measurements every expected value below comes from.

## Global Constraints

- Never write to `thermal.zarr`, `visible.mp4`, `metadata.json`, `events.json`, or any camera setting.
- No new dependencies. The plot uses Pillow only, as `analysis/run_summary.py:6` does.
- ffmpeg/ffprobe come from `find_ffprobe(FFMPEG_CANDIDATES)` / `find_ffprobe()` (`visible/rtsp.py:103`, `visible/recorder.py:44`).
- Decode with `-fps_mode passthrough`: one decoded frame per packet. The default mode inserts a duplicate frame (6,193 frames instead of 6,192).
- Skip each segment's first `FRAME0_SKIP_S` (`playback/visible_timing.py`).
- Flash rule: non-keyframe `brightening ≥ max(15, median + 6 × max(MAD, 1))` (MAD = 1.4826 × median absolute deviation over non-keyframes); merge flagged frames within 1.0 s.
- Analysis region = the sample ROI mapped into visible pixels, grown by 30 px.
- Threshold = Otsu over the region's pixels in the first 5 s of analysed frames, then fixed for the run.
- Output says "flash at the sample", never "arc" or "spark".
- A step failure is logged and skipped; it never blocks Stop (pattern in `api/app.py:436–455`).
- Code style: ruff (line length 100), mypy strict, type hints and docstrings, `logger = logging.getLogger(__name__)`, no `print`.
- Red-green TDD for every logic change. Fixtures are captured from `20261020_144402_Run`, never invented. The one synthetic clip (Task 4) tests decode plumbing only, and its test says so.

## Review Focus

1. **Visible video starts late or has several segments** (recorder restarts, `visible_001.mp4`): the times must stay on the thermal axis per segment. Task 4 test `test_runner_multi_segment_times_use_each_segment_start`.
2. **Sample ROI is a circle or rect, not a polygon**: it still maps and analyses. Task 1 test `test_roi_outline_circle_and_rect`.
3. **Sample ROI maps partly or fully outside the 1280×960 frame** (bad alignment): clip, or `status: skipped` with a reason, never a crash. Task 1 test `test_region_mask_outside_frame_returns_none`, Task 4 test `test_runner_skips_when_roi_outside_frame`.
4. **Run with no flagged frames**: `events: []` with coverage filled, and the UI says "0 flashes over …", not nothing. Task 3 test `test_find_events_none`, Task 7 test `statusText ok with zero events`.
5. **Re-running on an old run whose exports already exist**: overwrite atomically, and leave no half-written CSV/JSON if it fails midway. Task 4 test `test_runner_writes_atomically_and_overwrites`.

---

### Task 1: Captured fixtures and ROI geometry

**Files:**
- Create: `backend/tests/fixtures/visible_sample_20261020_144402.npz`, `backend/tests/fixtures/visible_sample_20261020_144402.json`
- Modify: `backend/tests/fixtures/README.md` (one paragraph per new fixture: source run, frames, how captured, "copied unchanged")
- Create: `backend/flir_research_interface/analysis/visible_sample.py`
- Test: `backend/tests/test_visible_sample.py`

**Interfaces:**
- Produces:
  - `pick_rois(rois: list[dict[str, Any]] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]`: (sample, bed). Sample = names containing "sample" (case-insensitive), smallest area wins. Bed = names containing "powder" or "bed". Only area kinds (polygon, rect, circle, ellipse) qualify.
  - `roi_outline_ir(roi: dict[str, Any], n_circle: int = 64) -> np.ndarray`: (N, 2) float IR-pixel outline.
  - `ir_to_visible_points(points: np.ndarray, h_matrix: list[list[float]], ir_size: tuple[int, int] = (640, 480), vis_size: tuple[int, int] = (1280, 960)) -> np.ndarray`: uses `inv(H)` with the basis change of `ir_to_visible_coeffs` (`visible_overlay.py:30`).
  - `region_mask(outline_vis: np.ndarray, margin_px: int, vis_size: tuple[int, int] = (1280, 960)) -> tuple[np.ndarray, tuple[int, int, int, int]] | None`: boolean mask cropped to its bbox `(x0, y0, w, h)` (even w and h, clipped to the frame). None when no pixel of the grown region lies in the frame. Rasterize with `PIL.ImageDraw.polygon`, then grow by the margin with a Euclidean distance test.

- [ ] **Step 1: Capture the fixtures.** Write a one-off capture script in the session scratchpad (not committed) that reads `"/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR/backend/experiments/20261020_144402_Run"` and saves:
  - `.json`: `visible_alignment` and `rois` from `metadata.json`, unchanged; `t_start_s` 25.996 and `host_t0_ns` 1792521838069768000; the packet table (`pts_time`, keyframe flag) for all 6,192 packets.
  - `.npz`:
    - `crops`: luma, cropped to the bbox `region_mask` produces for `freehand_sample` (expected ≈128×130), for frames 3170 (≈300 s), 6141, 6142, 6143, plus the 24 frames of the first 5 s after the 0.25 s skip (indices 3–26, t 26.48–31.4 s, for the threshold);
    - `crop_frames`: their frame indices;
    - `brightening`: the per-frame brightening series of all 6,192 frames, computed by this design's region and definition;
    - `keyframe`: the per-frame keyframe flags.

  Document in README that `brightening` is derived from the real video by the capture script (formula stated).
- [ ] **Step 2: Write failing tests.**
  - `test_pick_rois_real_run`: on the fixture rois, sample is id 101 (`freehand_sample`), bed is id 94 (`powder`).
  - `test_pick_rois_smallest_sample_wins`: two "sample" polygons → the smaller one.
  - `test_pick_rois_none`: `[]`, `None`, and a run with only a spot named "sample" → `(None, None)`.
  - `test_freehand_sample_maps_onto_video_sample`: mapped outline bbox x 347–411, y 405–469 (±2 px).
  - `test_roi_outline_circle_and_rect`: a circle {cx 147, cy 216, r 67} gives 64 points all at distance 67 from the centre; a rect {x0 1, y0 0, x1 5, y1 4} gives its 4 corners.
  - `test_region_mask_margin_and_even_bbox`: for the mapped `freehand_sample` with margin 30, mask.sum() = 13,543 ± 1 % and w, h are even.
  - `test_region_mask_outside_frame_returns_none`: an outline entirely at x > 1400 → None; one straddling the left edge → a bbox with x0 = 0.
- [ ] **Step 3: Run** `cd backend && uv run pytest tests/test_visible_sample.py -v`. Expected: FAIL (ImportError: module `analysis.visible_sample` has no attribute `pick_rois`).
- [ ] **Step 4: Implement the four functions** in `analysis/visible_sample.py`.
- [ ] **Step 5: Run the tests.** Expected: 7 PASS. Then `uv run ruff check . && uv run mypy flir_research_interface/analysis/visible_sample.py`: clean.
- [ ] **Step 6: Commit** `feat(visible): map the sample ROI into the visible frame` (fixtures, README, module, tests).

### Task 2: Threshold and per-frame metrics

**Files:** Modify `analysis/visible_sample.py`; Test `tests/test_visible_sample.py`

**Interfaces:**
- Consumes: Task 1's `region_mask` output (mask, bbox) and the `.npz` crops.
- Produces:
  - `otsu_threshold(values: np.ndarray) -> int`: 0–255 over a 256-bin histogram.
  - `FrameMetrics` (`@dataclass(frozen=True)`): `sample_dark_px: int` (pixels with luma < threshold), `sample_mean_luma: float | None`, `bed_clipped_frac: float | None`, `brightening: float | None`.
  - `frame_metrics(luma: np.ndarray, prev: np.ndarray | None, region: np.ndarray, threshold: int, bed: np.ndarray | None = None) -> FrameMetrics`: `luma`/`prev` are uint8 crops of the same bbox. `brightening` = 99.5th percentile of `int16(luma) − int16(prev)` over `region`, None when `prev` is None. `prev` is the previous **analysed** frame of the same segment (frames inside the 0.25 s skip are never used), so each segment's first analysed frame has `brightening = None`. The Task 1 capture script computes the fixture `brightening` series by this same definition (NaN where None).

- [ ] **Step 1: Write failing tests.**
  - `test_otsu_threshold_real_first_5s`: on the fixture's 24 first-5 s crops (region pixels pooled), the threshold is 178 (exact; Otsu = argmax of between-class variance over 256 bins).
  - `test_dark_area_real_start`: "dark" means luma **strictly below** the threshold. With 178, the mean `sample_dark_px` over those 24 frames is 1,095 ± 1 %, and frame 3 alone is 1,100 ± 1 %.
  - `test_brightening_glow_frames`: frame 6142 vs 6141 → 97 ± 1; 6143 vs 6142 → 27 ± 1; 6141 vs its own copy → 0.
  - `test_frame_metrics_no_prev`: `brightening is None`.
  - `test_bed_clipped_frac`: a bed mask over an all-255 crop → 1.0; no bed → None.
- [ ] **Step 2: Run.** Expected: FAIL (`otsu_threshold` not defined).
- [ ] **Step 3: Implement `otsu_threshold`, `FrameMetrics`, `frame_metrics`.**
- [ ] **Step 4: Run.** Expected: PASS; ruff and mypy clean.
- [ ] **Step 5: Commit** `feat(visible): per-frame sample area and brightening`.

### Task 3: Flash threshold, events, coverage

**Files:** Modify `analysis/visible_sample.py`; Test `tests/test_visible_sample.py`

**Interfaces:**
- Produces:
  - `flash_threshold(brightening: np.ndarray, keyframe: np.ndarray, floor: float = 15.0, k: float = 6.0, mad_floor: float = 1.0) -> float`: NaNs and keyframes are ignored. An empty input returns `floor`.
  - `find_events(t_s: np.ndarray, brightening: np.ndarray, keyframe: np.ndarray, threshold: float, merge_s: float = 1.0) -> list[dict[str, Any]]`: each event is `{"t_start_s", "t_peak_s", "t_end_s", "peak_brightening", "n_frames", "peak_frame"}`. `peak_frame` is the array index; bbox is added by the runner.
  - `coverage(t_s: np.ndarray) -> dict[str, Any]`: `{"frames_analysed", "t_first_s", "t_last_s", "gaps_over_300ms"}`.

- [ ] **Step 1: Write failing tests** (fixture `brightening`, `keyframe`, packet pts → `t_s = 25.996 + pts − pts[0]`):
  - `test_flash_threshold_real_run_floor_binds`: 15.0.
  - `test_find_events_real_run_three_events`: exactly 3 events. Spans 553.95–554.06, 615.66–615.85, 627.77–629.41 (±0.02 s). Peaks 20, 19, 97 (±1) at frames 5303, 6005, 6142. n_frames 2, 2, 7.
  - `test_find_events_no_event_at_glitch`: no event spans 413.3–414.0 s.
  - `test_find_events_merge_window`: with `merge_s=0.5`, event 3 splits into 2 (a regression guard for the measured 0.517 s gap).
  - `test_keyframes_never_flag`: set every keyframe's brightening to 200 → still the same 3 events.
  - `test_flash_threshold_mad_zero`: all-equal input → `max(15, median + 6)`, no ZeroDivision.
  - `test_find_events_none`: all-zero brightening → `[]`.
  - `test_coverage_real_run`: pass the analysed frames only (index ≥ 3, after the 0.25 s skip): gaps_over_300ms = 61 (one of the run's 62 gaps falls inside the skipped first 0.25 s), frames_analysed = number of rows passed.
- [ ] **Step 2: Run.** Expected: FAIL (`flash_threshold` not defined).
- [ ] **Step 3: Implement.** `find_events` groups flagged frames in time order: a flagged frame joins the open event when `t − t_last_flagged ≤ merge_s`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(visible): flash events at the sample`.

### Task 4: Runner (decode, segments, files, statuses, close-up)

**Files:**
- Create: `backend/flir_research_interface/analysis/visible_sample_run.py`
- Test: `backend/tests/test_visible_sample_run.py`

**Interfaces:**
- Consumes: Tasks 1–3; `ExperimentReader` (`reader.visible`, `reader.metadata`, `reader.host_t0_ns`, `reader.path`); `thermal_segments(reader.visible, reader.host_t0_ns)`.
- Produces:
  - `analyse_visible_sample(reader: ExperimentReader, ffmpeg: str | None = None, ffprobe: str | None = None, closeup: bool = True) -> dict[str, Any]`: returns the summary written to `exports/visible_sample.json`.
    - Summary keys: `status` (`ok`|`skipped`|`failed`), `reason` (str|None), `software`, `sample_roi` {id, name}, `bed_roi` {id, name}|None, `bbox`, `margin_px` 30, `threshold`, `flash_threshold`, `rule` {floor 15, k 6, mad_floor 1, merge_s 1.0}, `coverage` (Task 3), `events` (Task 3 events + `bbox` of 16×16 blocks with the largest positive change at the peak frame), `stretch` {lo, hi 250}, `files` [names written].
    - When ok it also writes `exports/visible_sample.csv` with columns `t_s,segment,frame,keyframe,sample_dark_px,sample_mean_luma,bed_clipped_frac,brightening` (empty cell for None), and `exports/visible_sample_closeup.mp4` (when `closeup`).
    - On skip or fail it writes only the JSON (with the reason) and removes any older CSV/MP4/PNG of this feature, so stale results never sit beside a skipped status.
  - Skip reasons (exact strings): `"no visible video"`, `"no visible alignment"`, `"no sample ROI (name containing 'sample')"`, `"sample ROI maps outside the visible frame"`, `"ffmpeg not found"`. Failed: `reason = "<ExceptionType>: <message>"`.
- Decode with `ffmpeg -v fatal -i <file> -vf extractplanes=y,crop=W:H:X:Y -fps_mode passthrough -f rawvideo -`, streamed in chunks. Get packet pts and K flags from `ffprobe -show_entries packet=pts_time,flags`. Fail when the decoded frame count ≠ packet count. The bbox covers the union of the sample region and the bed region.
- Close-up: `crop` (square, centred on the sample region, even size), `lutyuv=y='clip((val-LO)*255/(250-LO),0,255)'` with LO = 1st percentile of sample dark-pixel luma over the run, `scale=3*W:3*W:flags=lanczos`, `-fps_mode vfr`, `libx264 -crf 20 -pix_fmt yuv420p`.
- Write CSV/JSON/MP4 to `<name>.part` and `os.replace` when complete.

- [ ] **Step 1: Write failing tests.**
  - Experiments are built with `Recorder` like `tests/test_export.py:_make_experiment`, but at 640×480 with real `visible_alignment` and `rois` from the fixture JSON.
  - The synthetic decode-plumbing clip comes from `ffmpeg -f lavfi -i color=white:s=1280x960:r=10 -t 3`, with a `drawbox` dark square at the mapped sample bbox from 1.0 s on, plus `-x264-params keyint=5`. Mark its test "synthetic: decode/timing plumbing only, not detection truth". Skip these tests when ffmpeg is missing.
  - `test_runner_skips_without_visible`, `test_runner_skips_without_alignment`, `test_runner_skips_without_sample_roi`, `test_runner_skips_when_roi_outside_frame`: status `skipped`, exact reason, only the JSON exists.
  - `test_runner_ok_synthetic_clip`: status ok. CSV rows = packets − frames in the first 0.25 s. `t_s` of row 0 = t_start + pts offset. `sample_dark_px` rises from ≈0 to > 0 at 1.0 s ± 0.1 s. `coverage.frames_analysed` matches the CSV. The close-up MP4 exists, and ffprobe reports width = height = 3 × its crop.
  - `test_runner_multi_segment_times_use_each_segment_start`: two clips as `visible.mp4` and `visible_001.mp4` with `segments` whose `first_frame_host_ns` differ by 50 s → the second clip's rows start at its own `t_start_s`.
  - `test_runner_writes_atomically_and_overwrites`: run twice → the files are replaced and no `.part` files remain. Third run with `ffmpeg="/nonexistent"` → status `skipped`, reason `"ffmpeg not found"` (an explicit path that is not an executable file counts as not found), older CSV/MP4/PNG removed. Fourth run with the decode helper monkeypatched to raise mid-stream → status `failed`, no `.part` files left, older CSV removed.
  - `test_runner_frame_count_mismatch_fails`: monkeypatch the probe to return one extra packet → `failed`, with "frame count" in the reason.
- [ ] **Step 2: Run** `uv run pytest tests/test_visible_sample_run.py -v`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement** `analyse_visible_sample` plus private helpers for probe, decode, write and close-up.
- [ ] **Step 4: Run.** Expected: PASS; ruff and mypy clean.
- [ ] **Step 5: Commit** `feat(visible): post-run visible sample analysis runner`.

### Task 5: Timeline plot (Pillow)

**Files:** Create `analysis/visible_sample_plot.py`; Modify `analysis/visible_sample_run.py` (write the PNG when ok); Test `tests/test_visible_sample_plot.py`

**Interfaces:**
- Consumes: `roi_series(reader, [sample_roi])` (`analysis/series.py`); `control_series_from_rows([e for e in reader.events if e.get("type") == "control"], reader.timeline())` (`analysis/control_series.py:51`); the CSV rows and summary from Task 4; `_nice_ticks` from `run_summary.py:186`.
- Produces: `visible_sample_plot_png(reader: ExperimentReader, rows: list[dict[str, Any]], summary: dict[str, Any]) -> bytes`.
  - Four stacked panels sharing the x axis: RF forward (W); sample ROI max and mean (°C), with a dotted line at the active case's high limit when the max reaches it; `sample_dark_px` (raw plus a 31-frame rolling median); `brightening` (keyframes omitted).
  - Every panel carries a vertical line at each event's `t_peak_s`, labelled with its peak value.
  - Same canvas size, colours and font as `roi_plot_png`. The x label reads "time since thermal frame 0 (s)".
- Written by the runner as `exports/visible_sample_plot.png` (`.part` + replace).

- [ ] **Step 1: Write failing tests.** `test_plot_png_decodes_with_events`: the bytes open with PIL, have the `roi_plot_png` size, and at the x pixel of an event line in the bottom panel there are pixels of the event colour. `test_plot_png_without_rf_or_events`: a run with no control events and no events still renders.
- [ ] **Step 2: Run.** Expected: FAIL (module not found).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. **Visual gate:** render the plot for the real run (Task 8) and compare it panel for panel with the spike figure.
- [ ] **Step 5: Commit** `feat(visible): visible sample timeline plot`.

### Task 6: Wire into the post-stop and derived jobs; expose the summary

**Files:** Modify `backend/flir_research_interface/api/app.py` (`_schedule_post_stop_exports` ~436, `export_derived_route` ~1571, `experiment_info` ~1481); Test `backend/tests/test_api_visible_sample.py`

**Interfaces:**
- Produces:
  - `_analyse_visible_sample(exp_dir: Path) -> None`: calls `analyse_visible_sample(ExperimentReader(exp_dir))`.
  - Post-stop order: ROI series → run summary → **visible sample analysis** → thermal preview video.
  - Derived job: a step `"visible sample"` after `"images"`.
  - `experiment_info` adds `info["visible_sample"]`: the parsed `exports/visible_sample.json`, or None when the file is absent or invalid.

- [ ] **Step 1: Write failing tests** (TestClient as in `tests/test_api_control_telemetry.py:15`):
  - `test_experiment_info_includes_visible_sample`: write a summary JSON into a run's exports → `GET /api/experiments/{name}` returns it under `visible_sample`.
  - `test_experiment_info_visible_sample_absent`: absent file → `visible_sample` is None.
  - `test_derived_job_runs_visible_step`: monkeypatch `analyse_visible_sample` to record the call → `POST /export/derived?video=false` and poll until done → called once.
  - `test_post_stop_visible_failure_does_not_break_chain`: monkeypatch it to raise → the thermal video step still runs.
- [ ] **Step 2: Run.** Expected: FAIL (KeyError `visible_sample`).
- [ ] **Step 3: Implement the wiring.**
- [ ] **Step 4: Run** the new tests plus `uv run pytest tests/test_api_derived.py -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(visible): run the sample analysis after each recording`.

### Task 7: Frontend marks and status line

**Files:**
- Create: `frontend/src/lib/visibleSample.ts`, `frontend/src/lib/visibleSample.test.ts`
- Modify: `frontend/src/lib/api.ts` (types), `frontend/src/lib/events.ts` (`MARKER_CATS`), `frontend/src/components/PlaybackPage.tsx:247`, `frontend/src/components/ExportSection.tsx` (status line in the exports block)

**Interfaces:**
- Produces:
  - `interface VisibleSampleEvent { t_start_s: number; t_peak_s: number; t_end_s: number; peak_brightening: number; n_frames: number; peak_frame: number; }`
  - `interface VisibleSampleSummary { status: "ok" | "skipped" | "failed"; reason: string | null; coverage?: { frames_analysed: number; t_first_s: number; t_last_s: number; gaps_over_300ms: number }; events?: VisibleSampleEvent[]; }`
  - `ExperimentInfo.visible_sample?: VisibleSampleSummary | null`
  - `visibleFlashMarkers(vs: VisibleSampleSummary | null | undefined): Marker[]`: one marker per event at `t_peak_s`, labelled `visible flash +<peak>`.
  - `visibleSampleStatusText(vs: VisibleSampleSummary | null | undefined): string | null`. Exact copy:
    - ok → `Visible sample: <n> flash(es) at the sample, <t_first>–<t_last> s analysed (<gaps> gaps > 0.3 s)`; n = 0 reads `0 flashes`;
    - skipped → `Visible sample: not analysed (<reason>)`;
    - failed → `Visible sample: analysis failed (<reason>)`;
    - absent → null.
  - `MARKER_CATS` gains `{ label: "visible flash", color: "var(--trace-5)", match: (l) => l.includes("VISIBLE FLASH") }`, placed before the gap entry.

- [ ] **Step 1: Write failing tests** in `visibleSample.test.ts`: markers from the real run's 3 events (t 554.06/615.66/627.77, labels `visible flash +20`, `+19`, `+97`); `[]` for skipped or absent input; `statusText` for ok with 3 events, ok with zero events (`0 flashes`), skipped, failed and null; `markColor("visible flash +97")` = `var(--trace-5)`.
- [ ] **Step 2: Run** `cd frontend && npm test`. Expected: FAIL (cannot find module `./visibleSample.ts`).
- [ ] **Step 3: Implement**, and merge the markers in `PlaybackPage` (`[...eventsToMarkers(...), ...visibleFlashMarkers(info?.visible_sample)]`, sorted by t). Show `visibleSampleStatusText` in the ExportSection's exports block when non-null.
- [ ] **Step 4: Run** `npm test` and `npx tsc --noEmit`. Expected: PASS, no type errors. **Browser gate** (not unit-testable): open playback of `20261020_144402_Run` in the dev preview. Confirm three marks in the `--trace-5` colour near 554, 616 and 628 s; ▶◆ jumps to them; the legend shows "visible flash"; the exports block shows `Visible sample: 3 flashes …`. Screenshot it.
- [ ] **Step 5: Commit** `feat(visible): show visible flashes as playback marks`.

### Task 8: Real-data run and docs

**Files:** Modify `docs/visible_camera.md` (new section "Exposure control and post-run sample analysis (2026-10-20)")

- [ ] **Step 1: Real-data integration run** (reads the run, writes only its `exports/`): `cd backend && uv run python -c "from pathlib import Path; from flir_research_interface.playback.reader import ExperimentReader; from flir_research_interface.analysis.visible_sample_run import analyse_visible_sample; import json; print(json.dumps(analyse_visible_sample(ExperimentReader(Path('/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR/backend/experiments/20261020_144402_Run'))), indent=1))"`. Expected: status ok, threshold 178 ± 2, the three events of the spec table, no event at 413.65 s, coverage 61 gaps over the analysed frames. Read `visible_sample_plot.png` and play `visible_sample_closeup.mp4`.
- [ ] **Step 2: Skip-path check on real runs:** run it on one real run without `visible.mp4` and on one without a "sample" ROI (pick from the experiments folder). Expected: `status: skipped` with the exact reasons.
- [ ] **Step 3: Write the docs section.**
  - The exposure findings: GenICam (249 nodes, none for visible exposure); ONVIF (initialised with `fliruser`; imaging offers Focus only on `video0`/`video1`); REST API and web UI (no exposure control; `/api/image/adjustment` is IR display scaling); resource tree (`/prod/res/` while httpResource is on; `.system.vcam` = OV5640 with no exposure; leave httpResource off because it allows unauthenticated reads); SSH out of scope.
  - What the post-run analysis writes, and its limits: the powder is unrecoverable; ≈10 fps with gaps; "flash" is not proof of an arc.
- [ ] **Step 4: Full verification:** `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy flir_research_interface`; `cd frontend && npm test && npx tsc --noEmit`. Expected: all pass, with no new warnings.
- [ ] **Step 5: Commit** `docs(visible): exposure-control findings and post-run sample analysis`.
