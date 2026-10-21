# Visible-Video Adjustments and Camera Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposure/brightness/contrast on the live and recorded visible video (raw kept, settings remembered per run), full-range display of the untagged camera stream, optional analysis on the adjusted video, and operator-side presets for visible, thermal-camera and display settings.

**Architecture:** One linear adjustment model implemented twice (Python `analysis/visible_adjust.py`, TS `lib/visibleAdjust.ts`) and pinned by a shared parity fixture. Backend: a lossless full-range re-wrap for playback, a per-run `visible_adjust.json` sidecar, the recording stamp, adjusted media export, a separate adjusted analysis, and a presets store in `calibration/presets.json`. Frontend: sliders and an SVG filter on the visible views, presets UI, and the analysis checkbox.

**Tech Stack:** Python 3.12, numpy, Pillow, FastAPI, ffmpeg@6; React + TypeScript, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-21-visible-adjust-and-presets-design.md` (approved 2026-10-21). Read it first; its "Inputs and their evidence" table holds the code citations used below.

## Global Constraints

- Never modify `visible.mp4` (or `visible_NNN.mp4`), `thermal.zarr`, or radiometric numbers. `metadata.json` is written only by `Recorder.start` at record time.
- Adjustment model: `g = 2**exposure_ev`; `slope = contrast*g`; `intercept = 0.5 - 0.5*contrast + brightness`; `y = clip(slope*x + intercept, 0, 1)` on [0,1] values, uint8 output rounded to nearest. Ranges: `exposure_ev` −3…+3 (default 0), `brightness` −0.5…+0.5 (0), `contrast` 0.25…4 (1).
- Browser applies it with an SVG `feComponentTransfer` (`type="linear"`, R/G/B, `color-interpolation-filters="sRGB"`), never CSS `brightness()`/`contrast()`.
- Display paths read the visible video as full range; playback uses `exports/visible_full_range.mp4` (`_001`… per segment), made by `ffmpeg -c copy -bsf:v h264_metadata=video_full_range_flag=1`.
- Thermal presets hold only `camera/controls.py` `WRITABLE_NODES`; camera settings are written only on an explicit operator action, never at startup, never while recording; `CurrentCase` is written last.
- Adjusted analysis writes `exports/visible_sample_adjusted.{csv,json,png}` and `visible_sample_adjusted_closeup.mp4`; `bed_clipped_frac` uses raw luma; the raw analysis stays the default and drives flash marks.
- ffmpeg/ffprobe via `find_ffprobe(FFMPEG_CANDIDATES)` / `find_ffprobe()`; tests use `/opt/homebrew/opt/ffmpeg@6/bin/…` and skip without ffmpeg.
- Style: ruff (100), mypy strict, docstrings, module logger, no print; files ≤ 800 lines (put new tests in new files; `tests/test_visible_sample_run.py` is near its limit).
- Red-green TDD for every logic change; fixtures captured from `20261020_144402_Run` where real data is involved; UI wiring verified by `tsc` plus the browser gate.

## Review Focus

1. **A run recorded before this feature** (no `visible_adjust`, no sidecar): playback shows neutral, analysis raw, nothing errors. Task 3 test `test_effective_adjust_neutral_for_old_run`.
2. **ffmpeg missing or the full-range build failing**: playback still plays the raw file, and the UI says the range is not corrected (never silently looks "fixed"). Task 2 test `test_visible_route_falls_back_to_raw_and_says_so`.
3. **Preset applied while recording**: thermal part refused, visible and display applied, message shown. Task 8 test `applyPlan while recording skips thermal`.
4. **Preset containing a node the camera no longer offers / an enum value not in `enum_options`**: rejected with a reason, nothing partially written. Task 6 test `test_preset_rejects_unknown_node_and_bad_enum`.
5. **Sliders moved after an adjusted analysis**: the adjusted status line says "sliders changed since". Task 9 test `adjustedStatus stale`.

---

### Task 1: Adjustment model (Python + TS) with a shared parity fixture

**Files:** Create `backend/flir_research_interface/analysis/visible_adjust.py`, `backend/tests/test_visible_adjust.py`, `backend/tests/fixtures/visible_adjust_parity.json`, `frontend/src/lib/visibleAdjust.ts`, `frontend/src/lib/visibleAdjust.test.ts`; Modify `backend/tests/fixtures/README.md`.

**Interfaces — Produces:**
- Python: `NEUTRAL: dict[str, float]`; `LIMITS: dict[str, tuple[float, float]]`; `validate_adjust(raw: Any) -> dict[str, float]` (raises `ValueError` out of range / wrong type; ignores `preset`/`based_on` keys, returning only the three numbers); `adjust_linear(a: Mapping[str, float]) -> tuple[float, float]`; `apply_adjust(u8: np.ndarray, a: Mapping[str, float]) -> np.ndarray` (uint8 in → uint8 out, any shape); `is_neutral(a) -> bool`.
- TS: `interface VisibleAdjust { exposure_ev: number; brightness: number; contrast: number }`; `NEUTRAL_ADJUST`; `ADJUST_LIMITS`; `clampAdjust(a): VisibleAdjust`; `adjustLinear(a): { slope: number; intercept: number }`; `applyAdjustU8(v: number, a): number`; `isNeutral(a): boolean`; `adjustEqual(a, b, eps = 1e-6): boolean`.

- [ ] **Step 1: Build the parity fixture.** `visible_adjust_parity.json`: `cases` = 8 settings (neutral; each control at both limits; two mixed, e.g. {−1, 0.05, 1.4} and {+1.5, −0.2, 0.6}) with `slope`/`intercept` computed from the Global Constraints formula, and `luma` = one 126-pixel row of the real crop `crops[1]` (frame 6141) from `visible_sample_20261020_144402.npz` with the expected uint8 output per case. README entry: the row is captured; the expected values follow the spec formula.
- [ ] **Step 2: Write failing tests.** Python `test_parity_table` (slope/intercept to 1e-12, uint8 outputs exact), `test_validate_rejects_out_of_range_and_bool`, `test_apply_keeps_shape_and_dtype`, `test_neutral_is_identity_on_real_row`. TS: the same parity table read with `fs.readFileSync` from `backend/tests/fixtures/visible_adjust_parity.json` (path relative to the test file), plus `clampAdjust` and `adjustEqual` cases.
- [ ] **Step 3: Run** `cd backend && uv run pytest tests/test_visible_adjust.py -v` and `cd frontend && npm test` → FAIL (modules missing).
- [ ] **Step 4: Implement both modules.**
- [ ] **Step 5: Run** both → PASS; ruff/mypy/tsc clean.
- [ ] **Step 6: Commit** `feat(visible): one exposure/brightness/contrast model in Python and TS`.

### Task 2: Full-range display paths

**Files:** Create `backend/flir_research_interface/visible/full_range.py`, `backend/tests/test_visible_full_range.py`; Modify `backend/flir_research_interface/api/app.py` (routes at ~2046 `/api/experiments/{name}/visible.mp4` and ~2054 `/visible/{index}`), `backend/flir_research_interface/visible/preview.py` (`mjpeg_command`), `backend/flir_research_interface/analysis/visible_overlay.py` (frame extraction ~line 106).

**Interfaces — Produces:**
- `full_range_copy(run_dir: Path, file: str, ffmpeg: str | None) -> Path | None`: returns `run_dir/"exports"/<stem>_full_range.mp4` mapping (`visible.mp4` → `visible_full_range.mp4`, `visible_001.mp4` → `visible_001_full_range.mp4`), building it once (staged `.part`, `os.replace`, a per-file lock) when missing or older than the source; `None` when ffmpeg is missing or the build fails (logged).
- Routes serve the copy when available, else the raw file, with response header `X-Visible-Range: full` or `X-Visible-Range: raw-untagged`. `GET /api/experiments/{name}` gains `visible_range: "full" | "raw-untagged" | null` (null when no visible video), computed without building.
- `mjpeg_command(...)` uses `-vf scale={width}:-2:in_range=full:out_range=full`.
- `visible_overlay.py` extraction adds `scale=in_range=full:out_range=full` before `fps=`.

- [ ] **Step 1: Failing tests.** `test_full_range_copy_tags_pc_and_keeps_packets` (synthetic 1 s clip made with ffmpeg lavfi, labelled synthetic: ffprobe `color_range=pc`, packet count and per-packet sizes identical to the source); `test_full_range_copy_reused_and_rebuilt_when_source_newer`; `test_visible_route_serves_full_range_copy` (TestClient, header `full`); `test_visible_route_falls_back_to_raw_and_says_so` (ffmpeg `/nonexistent` → raw bytes, header `raw-untagged`, `visible_range` matches); `test_mjpeg_command_reads_full_range`; `test_overlay_extraction_reads_full_range` (argv contains `in_range=full`).
- [ ] **Step 2: Run** `uv run pytest tests/test_visible_full_range.py -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; run `tests/test_visible_overlay.py` and the preview tests too.
- [ ] **Step 5: Commit** `fix(visible): show the camera's full-range video as full range`.

### Task 3: Per-run sidecar, recording stamp, effective adjustment

**Files:** Create `backend/flir_research_interface/visible_adjust_store.py`, `backend/tests/test_visible_adjust_store.py`; Modify `backend/flir_research_interface/api/app.py` (`RecordingStartRequest` ~106, recording start/arm to pass `extra`, new routes, `experiment_info`), `backend/flir_research_interface/storage.py` (`MUTABLE_PATHS`).

**Interfaces — Produces:**
- `SIDECAR = "visible_adjust.json"`; `read_sidecar(run_dir) -> dict | None` (tolerant); `write_sidecar(run_dir, adjust: dict) -> dict` (validated via `validate_adjust`, atomic like `labels.py`, stores `{exposure_ev, brightness, contrast, saved_utc}`); `delete_sidecar(run_dir) -> bool`; `effective_adjust(run_dir, metadata) -> tuple[dict[str, float], str]` → (values, source ∈ `"sidecar" | "recorded" | "neutral"`).
- `RecordingStartRequest.visible_adjust: VisibleAdjustIn | None` (`exposure_ev`, `brightness`, `contrast`, `preset: str | None`, `based_on: str | None`); start and arm pass `extra={"visible_adjust": …}` to `Recorder.start` when given.
- Routes: `PUT /api/experiments/{name}/visible-adjust` (body: the three numbers + `library`), `DELETE /api/experiments/{name}/visible-adjust?library=…`; `experiment_info` adds `visible_adjust` (effective values + `source`) and `visible_adjust_recorded` (`metadata.visible_adjust` or null).
- `MUTABLE_PATHS = ("labels.json", "visible_adjust.json", "exports/*")`.

- [ ] **Step 1: Failing tests.** `test_effective_adjust_prefers_sidecar_then_recorded_then_neutral`; `test_effective_adjust_neutral_for_old_run`; `test_write_sidecar_atomic_and_validated` (out-of-range → ValueError, no file); `test_tolerant_read_of_corrupt_sidecar`; `test_recording_start_stamps_visible_adjust` (simulated backend via TestClient, then `metadata.json` has the block incl. `preset`/`based_on`); `test_put_and_delete_visible_adjust_route` (incl. library argument); `test_mutable_paths_include_sidecar`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new file plus `tests/test_api_recording.py`, `tests/test_storage*.py` → PASS.
- [ ] **Step 5: Commit** `feat(visible): remember the visible adjustment per run`.

### Task 4: Media export uses the run's adjustment

**Files:** Modify `backend/flir_research_interface/analysis/visible_overlay.py`, `backend/flir_research_interface/analysis/media.py` (where `VisibleSource` is built); Test `backend/tests/test_visible_overlay_adjust.py`.

**Interfaces:** `VisibleSource(..., adjust: Mapping[str, float] | None = None)` applies `apply_adjust` to each extracted RGB frame before warping/caching; `media.py` passes `effective_adjust(...)[0]` (skip when neutral).

- [ ] **Step 1: Failing tests:** a `VisibleSource` built on a synthetic grey clip (labelled synthetic) with `{exposure_ev: 1}` returns frames whose values equal `apply_adjust` of the unadjusted frames; neutral returns identical frames; `media.py` passes the run's sidecar values (monkeypatch `VisibleSource` to capture the argument).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS (also `tests/test_visible_overlay.py`, `tests/test_media*.py`).
- [ ] **Step 5: Commit** `feat(visible): exported clips show the run's visible adjustment`.

### Task 5: Analysis on the adjusted video (separate result)

**Files:** Modify `backend/flir_research_interface/analysis/visible_sample_run.py`, `visible_sample.py` (only if `frame_metrics` needs a raw-luma argument for `bed_clipped_frac`), `api/app.py` (derived route param, `experiment_info`); Test `backend/tests/test_visible_sample_adjusted.py`.

**Interfaces — Produces:**
- `analyse_visible_sample(reader, ffmpeg=None, ffprobe=None, closeup=True, adjust: Mapping[str, Any] | None = None)`: when `adjust` is given, results go to the `visible_sample_adjusted` file family (JSON, CSV, PNG, close-up(s) `visible_sample_adjusted_closeup*.mp4`); luma passes through `apply_adjust` before threshold, dark area, mean, brightening and the close-up; `bed_clipped_frac` uses raw luma; the summary adds `adjust: {exposure_ev, brightness, contrast, source}`. Stale-file cleanup touches only the family being written.
- Close-up `lutyuv` composes adjustment then stretch: `clip(((clip(slope*val+intercept*255,0,255))-LO)*255/(250-LO),0,255)` with LO computed on adjusted luma.
- `POST /export/derived?visible_adjusted=true` additionally runs the adjusted analysis with the run's effective adjustment (raw analysis runs as before). `experiment_info` adds `visible_sample_adjusted` (parsed JSON or null).

- [ ] **Step 1: Failing tests** (fixture crops via the existing lossless-encode helper in `tests/visible_sample_helpers.py`): neutral adjust → adjusted JSON equals raw on every measured field except `adjust`; `{exposure_ev: -1}` → threshold and dark area change, `bed_clipped_frac` identical to raw; raw files untouched by an adjusted run and vice versa; derived route with `visible_adjusted=true` produces both families; `experiment_info.visible_sample_adjusted` present.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS (plus the existing visible_sample test files).
- [ ] **Step 5: Commit** `feat(visible): optional visible analysis on the adjusted video`.

### Task 6: Presets store and API

**Files:** Create `backend/flir_research_interface/presets.py`, `backend/tests/test_presets.py`; Modify `api/app.py` (routes).

**Interfaces — Produces:**
- `PRESETS_FILE = "presets.json"` in `calibration_dir(experiments_root)`; `load_presets(root) -> dict`; `save_preset(root, preset: dict, *, enum_options: dict[str, list[str]] | None, n_cases: int | None) -> dict`; `delete_preset(root, name)`; `rename_preset(root, old, new)`; `set_last_applied(root, name | None)`. Preset = `{name (1–60 chars), visible_adjust, thermal: {node: value} ⊆ WRITABLE_NODES, display: {palette, range: {mode: "auto"} | {mode: "locked", min_c, max_c}}, saved_utc}`; thermal validated with `camera/controls.py` `validate_values` when `enum_options` is given; unknown nodes rejected always.
- `thermal_from_camera_info(info: dict) -> tuple[dict[str, Any], list[str]]` → (writable values, names left out because `None`/absent); handles Spinnaker (`nodes.IRFrameRate`, `active_case.index`, `nuc_mode`, `object_parameters`) and simulated (`ir_frame_rate`) shapes; drops `EstimatedTransmission`, `UseWindowTemperature`.
- Routes: `GET /api/presets`; `PUT /api/presets/{name}`; `DELETE /api/presets/{name}`; `POST /api/presets/{name}/rename` (body `new_name`); `POST /api/presets/last-applied` (body `name | null`); `GET /api/presets/current-thermal` → `thermal_from_camera_info(camera_info)` (409 when not connected).

- [ ] **Step 1: Failing tests:** round-trip save/load; `test_preset_rejects_unknown_node_and_bad_enum`; rename updates `last_applied`; delete clears it; tolerant read of a corrupt file; `thermal_from_camera_info` on the simulated backend's real `camera_info()` output and on a Spinnaker-shaped dict built from the 2026-10-20 values in the spec (test says shape-only); routes incl. 409 for current-thermal without a camera.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(presets): save visible, camera and display settings as named presets`.

### Task 7: Frontend sliders, filter, playback sidecar, recording stamp

**Files:** Modify `frontend/src/lib/layout.ts` (persist `visibleAdjust`), `frontend/src/components/VisiblePanel.tsx` (sliders + SVG filter on `VisibleLive`/`VisibleVideo`), `frontend/src/components/PlaybackPage.tsx` (effective adjust, debounced PUT, reset → DELETE, show `visible_range`), `frontend/src/components/RecordPanel.tsx` (+ `api.recordingStart`/`recordingArm` param), `frontend/src/lib/api.ts` (types/routes); Create `frontend/src/lib/visibleAdjustUi.ts` + test.

**Interfaces — Produces:** `svgFilterId(a): string` and `filterTableValues(a): { slope: string; intercept: string }` (formatted from `adjustLinear`); `recordStamp(current: VisibleAdjust, lastApplied: { name: string; visible_adjust: VisibleAdjust } | null): { exposure_ev; brightness; contrast; preset: string | null; based_on: string | null }` (preset name only when `adjustEqual`); `rangeNote(visible_range): string | null` (`"visible video shown without range correction"` for `raw-untagged`).

- [ ] **Step 1: Failing tests** (`visibleAdjustUi.test.ts`): `recordStamp` match / modified / no preset; `filterTableValues` equals `adjustLinear`; `rangeNote`; layout load/save round-trips `visibleAdjust` and falls back to neutral on garbage.
- [ ] **Step 2–4:** run `npm test` → FAIL, implement, run → PASS; `npx tsc --noEmit`, `npm run build`.
- [ ] **Step 5: Commit** `feat(visible): exposure, brightness and contrast sliders for live and recorded video`.

### Task 8: Frontend presets

**Files:** Create `frontend/src/lib/presets.ts` + test, `frontend/src/components/PresetPicker.tsx`; Modify `VisiblePanel.tsx` (live: picker with save/apply/rename/delete; playback: "apply look" only), `CameraControls.tsx` ("save current as…"), `App.tsx` (startup restore of palette/range from `last_applied` when the browser has nothing stored; persist palette/range in layout), `api.ts`.

**Interfaces — Produces:** `applyPlan(preset, state: { recording: boolean; cameraConnected: boolean; enumOptions }) -> { visible; display; thermal: Array<[node, value]> | null; skipped: string[]; warnings: string[] }` (thermal null while recording or disconnected; `CurrentCase` last; warning "changing the measurement case triggers a NUC" when it changes); `isModified(current, preset): boolean`; `presetFromState(name, visible, display, thermal, omitted)`.

- [ ] **Step 1: Failing tests:** `applyPlan while recording skips thermal` (with message), disconnected skips thermal, `CurrentCase` ordered last with the warning, unchanged values omitted from the write, enum not in options reported in `skipped`; `isModified`; `presetFromState` excludes `null` thermal values and lists them.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS; tsc, build.
- [ ] **Step 5: Commit** `feat(presets): pick, save and apply presets in the app`.

### Task 9: Frontend adjusted-analysis checkbox and status

**Files:** Modify `frontend/src/components/ExportSection.tsx`, `frontend/src/lib/visibleSample.ts` (+ test), `frontend/src/lib/api.ts` (`exportDerived(name, video, visibleAdjusted)`).

**Interfaces — Produces:** `adjustedStatusText(vsAdj, currentAdjust): string | null` → `Visible sample (adjusted: exposure <e> EV, brightness <b>, contrast <c>): …` reusing `visibleSampleStatusText`'s body; appends `; sliders changed since` when `!adjustEqual(vsAdj.adjust, currentAdjust)`; null when absent.

- [ ] **Step 1: Failing tests:** `adjustedStatus` fresh / `adjustedStatus stale` / absent / skipped (reason shown).
- [ ] **Step 2–4:** run → FAIL, implement (checkbox remembered in browser storage; regenerate buttons pass it), run → PASS; tsc, build.
- [ ] **Step 5: Commit** `feat(visible): run and show the adjusted visible analysis`.

### Task 10: Real-data gates and docs

**Files:** Modify `docs/visible_camera.md`.

- [ ] **Step 1: Real data** (writes only the run's `exports/`): on `/Volumes/FLIR SSD/FLIR-recordings/20261020_144402_Run` build the full-range copy (ffprobe `color_range=pc`, same packet count as `visible.mp4`), then run the adjusted analysis with `{exposure_ev: -1, brightness: 0, contrast: 1.4}` and report it beside the raw result (threshold, events, `bed_clipped_frac` unchanged).
- [ ] **Step 2: Browser gate** (controller; camera-free server, `FRI_NO_AUTOCONNECT=1`): playback of that run — draw a frame to a canvas and read back two pixels with raw Y 245 and 255 (positions from the raw frame), which must differ; move sliders → the view changes and `visible_adjust.json` appears; reset → it is removed; preset "apply look" writes the sidecar; an exported clip shows the adjustment; the adjusted analysis checkbox produces the second status line.
- [ ] **Step 3: Docs:** a section on the adjustments, the full-range finding (measured numbers), presets, and what is untested on hardware (live preview, recording stamp, preset apply to the camera).
- [ ] **Step 4: Full verification:** backend pytest, ruff, mypy; frontend npm test, tsc, build.
- [ ] **Step 5: Commit** `docs(visible): adjustments, full-range display and presets`.
