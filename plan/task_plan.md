# Task Plan: FLIR Research Interface — Session 1 (Milestone 0 + 1 + simulated backend)

## Goal
Deliver a project skeleton, docs/architecture.md, docs/radiometry.md (evidence-only), a
Milestone-1 camera probe, and a TDD-built simulated camera backend; then STOP and request
the probe output from the real A70 before touching radiometric node names.

## Phases
- [x] Phase 1: Inspect environment (dir empty; Spinnaker 3.1.0.79 x86_64 installed; arm64 Mac; no x86 Python)
- [x] Phase 2: Research (Spinnaker A50/A70 support, latest SDK/macOS arm64, PySpin Python versions,
      public FLIR GenICam radiometric node docs, timestamp semantics) -> plan/notes.md
- [x] Phase 3: Project skeleton (git init, backend/ pkg, tests, docs, scripts, examples)
- [x] Phase 4: TDD — camera abstraction (base.py) + SimulatedCameraBackend
- [x] Phase 5: Camera probe utility (PySpin-dependent, discovery-only, no assumed node names)
- [x] Phase 6: docs/architecture.md, docs/radiometry.md, docs/installation.md (probe instructions), README
- [x] Phase 7: Verify (pytest, ruff, probe --simulated smoke run), commit, closeout report

## Key Questions
1. Does Spinnaker officially support the FLIR A70 R&D/Image Streaming? Which SDK version? (web verify)
2. Is there a native Apple-Silicon Spinnaker + PySpin build, or must we run x86_64 Python under Rosetta?
3. Which GenICam nodes expose radiometric/temperature-linear output on A50/A70? (public docs only; mark UNKNOWN otherwise)
4. What timestamp does Spinnaker deliver for GigE frames (device tick vs host)?

## Decisions Made
- Project directory: this FLIR folder (Dropbox). Repo name in-tree: flir-research-interface.
- Python package name: `flir_research_interface` (spec's tree shows rfam_thermal; spec says app is FLIR Research Interface).
- Planning files live in plan/ (user workspace convention).
- camera/spinnaker.py is a deliberate placeholder: no node names assumed until probe output is reviewed.
- Radiometric (signal-linear) host-side conversion is out of scope for v1; temperature-linear only.
- Python env: uv + Python 3.12 (PySpin 4.4 supports 3.10-3.12; 3.9 deprecated).

## Errors Encountered
- hatchling: `readme = "../README.md"` rejected (must be inside project dir) -> removed readme field from backend/pyproject.toml.

## Outstanding tasks (as of 2026-09-01 evening)

### Blocked on the user
- [ ] P0 Research Studio comparison (software equivalence): fri-live vs Research Studio on available scenes (room temperature, a warm object such as a hand/laptop/coffee mug), same case/object params -> docs/validation.md table. No hot targets exist; the camera's 3 factory cases ARE the calibration, we never do our own.
- [ ] P0 Free disk space on the acquisition Mac (~2.9 GiB free; recording needs ~1.1 GB/min raw).
- [ ] P2 (optional) `brew reinstall libbluray` or `brew reinstall ffmpeg` to repair the broken Homebrew ffmpeg 7.

### Development (next milestones)
- [x] M3 Live view (DONE 2026-09-01 evening; verified in browser against the A70: 30 fps camera, ~15 fps display, palettes, auto/lock range, hover readout, setup page with SDK check + discovery + connect):
  1. acquisition/service.py: camera thread, newest-wins viz slot, counters, state machine (TDD, simulated backend)
  2. api/app.py: FastAPI REST (/api/health, /api/setup/sdk, /api/setup/discovery, /api/camera/{connect,disconnect,info,status}) + WS /ws/frames (JSON header + uint16 LE counts, <=15 Hz) (TDD, TestClient)
  3. frontend/: Vite+React+TS; palette LUTs, counts->C, autoscale in pure TS modules tested with `node --test`; canvas view, hover readout, status bar, setup page
  4. e2e: browser against simulated camera, then real A70
  Decisions: palette applied client-side only; server never sends colorized data; viz drops counted, never silent; recording not in M3.
- [x] M4 Recording (2026-09-01): Zarr v2 (docs/data_format.md); recorder + API + UI verified on the A70 (291 frames, 0 drops). Camera-controls panel (case/object params/NUC/frame rate, block-while-recording) still TODO -> fold into M6/M8.
- [x] M5 Playback (2026-09-01): ExperimentReader (read-only), experiments/timeline/frame endpoints, Experiments + Playback pages (scrub, play/pause, step, speed, keyboard), store hash unchanged after playback.
- [x] UI plan 1 (2026-09-02, branch feat/ui-studio): tokens+fonts, layout reducer, Studio shell, live/playback in frame, previews (preview.png/keyframes.png/previews.json), reveal endpoint, experiments card grid with hover-scrub. Remaining plans: deployment (site + operator), camera controls.
- [ ] M6 ROI/plots (+ camera-controls panel), M7 export, M8 experiment metadata/events.
- [ ] M9 Visible camera recorder (RTSP /avc/ch1 H.264 1280x960 via ffmpeg -c copy; host-clock alignment).
- [ ] M10 Packaging + mDNS hostname + installer that prompts for the right Teledyne download.

### Open technical unknowns (docs/radiometry.md s10)
- [ ] Out-of-range/saturation encoding in temperature-linear counts.
- [ ] Temperature-linear stream behaviour during NUC and range switch (gaps? stale frames?).
- [ ] Content of the 3 extra sensor rows (HeightMax 483 vs 480); whether Focus nodes act on this lens.

## Status
**Session 4 end:** Milestone 1 DONE. Milestone 2 tooling DONE: SpinnakerCameraBackend (hardware tests pass), analysis/stats.py, `fri-live` validation CLI (149 frames @30.03 fps, 0 lost/dropped). BLOCKED on user: Research Studio side-by-side comparison at >=3 temperatures (docs/validation.md table). Disk ~2.9 GiB free — must be freed before Milestone 4 recording. Next dev: Milestone 3 live view (FastAPI + WebSocket + React) once validation table has at least one row. Next session: review probe_report.json, then implement camera/spinnaker.py and Milestone 2 validation.

## M6 ROI / plots (started 2026-09-02, on main after merging feat/ui-studio)
Design: ROI stats computed client-side from decoded counts (live + playback, no protocol change);
whole-recording traces from `GET /api/experiments/{name}/series` over the Zarr store; events
from events.json as markers. Camera-controls rail section follows as its own step.
- [x] 1 lib/roi.ts (reducer, normalizeRect, roiStats, persistence) — TDD
- [x] 2 lib/plot.ts (niceTicks, TraceBuffer, ranges, windows) — TDD
- [x] 3 backend analysis/series.py + /series endpoint — TDD
- [x] 4 ThermalView: ROI overlay canvas + spot/rect tools + select/delete
- [x] 5 TimePlot component in PlotDock (traces, events, cursor, window select)
- [x] 6 Wire live (App): rois state, per-frame stats, measurements rows, live traces
- [x] 7 Wire playback: per-frame stats, series fetch, cursor, events
- [x] 8 Gate (frontend tests, backend tests, ruff, mypy, browser check), commit
- [x] 9 Camera controls section (case, object params, NUC, frame rate) with recording lock

## M7 exports (DONE 2026-09-02): analysis/export.py + endpoints + playback export section + card export; docs/data_format.md.
## M8 metadata & events (started 2026-09-02)
- [x] 1 Recorder.note_event stamps frame_id; POST /api/recording/event (409 unless recording) — TDD
- [x] 2 PATCH /api/experiments/{name}/metadata merges `experiment` keys atomically, keeps an edit log — TDD
- [x] 3 eventsToMarkers uses frame_id when present (exact placement) — TDD
- [x] 4 UI: RECORDING section "mark event" (RF ON / RF OFF / custom + note); playback experiment section editable
- [x] 5 Gate + browser check + commit (244dbf7)

## M9 visible camera (core DONE 2026-09-02, hardware verification pending)
- [x] visible/recorder.py: ffmpeg stream copy of /avc/ch1 with wall-clock timestamps, graceful 'q' stop, visible.json sidecar; tested with a fake process
- [x] POST /api/recording/start {visible: true}; status/manifest/experiment info carry `visible`; RECORDING section checkbox
- [ ] On the A70: record 30 s with visible video, confirm visible.mp4 plays, duration matches, compare visible.json start time vs first thermal host timestamp
- [ ] Playback: show visible.mp4 beside/overlaid on the thermal image (needs FOV registration)

## Next: deployment (spec §6) — GitHub Pages site + operator packaging + PWA offline; blocked on the GitHub repo existing (gh repo create refused by the sandbox; user runs it)

## 2026-09-02 (later): camera connect failure fixed on the A70
- Cause: after re-plugging the USB adapter the camera announced current IP 0.0.0.0 in DISCOVERY_ACK while
  answering from 192.168.7.2; Spinnaker refused (GevDeviceIsWrongSubnet) and a leaked reference aborted
  ReleaseInstance. Fix: gvcp.diagnose + FORCEIP (setup page button, POST /api/setup/force-ip); connect
  releases SDK refs on refusal. Verified: 5/5 hardware tests, live 30 fps in the UI, camera node writes + NUC.
- Deployment plan progress: operator CORS/private-network/X-FRI-Client + api_version handshake (backend),
  lib/operator.ts (base URL, handshake). Still to do: api.ts on the operator base + client header, site-mode
  first-run screen (install operator / detect), PWA manifest + service worker, Pages + CI workflows,
  operator installers (launchd/systemd/Windows service), SDK install job from the private artifact URL.
- Disk on the acquisition Mac is ~1-3 GB free: recording refuses below 2 GB.

## Deployment (spec §6) — status 2026-09-02 evening
- [x] Operator: CORS (localhost + site origin), private-network preflight, X-FRI-Client on cross-origin writes, api_version handshake
- [x] Site mode UI (VITE_SITE_MODE=1): operator base URL, OperatorGate first-run page, PWA shell, CI + Pages workflows
- [x] Verified: site on :5174 drove the operator on :8000 with the real A70; 403 without the client header, 200 with it
- [ ] Pages needs the repo public (or a paid plan); set `site_origin` in fri-serve to https://mattlmccoy.github.io once live
- [ ] Operator packaging: launchd (.pkg) / Windows service (.msi) / systemd unit; menu-bar item; release feed
- [ ] SDK install job from the private artifact URL + sdk-manifest.json (spec §6.2 step 4)
- [ ] Safari ws:// fallback (redirect to the local copy)
- [ ] M9 follow-up: playback of visible.mp4 beside thermal; decide whether ~12 fps (throttled by the GigE stream) is acceptable or use /avc/ 640x480
