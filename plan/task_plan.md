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

## Status
**Session 4 end:** Milestone 1 DONE. Milestone 2 tooling DONE: SpinnakerCameraBackend (hardware tests pass), analysis/stats.py, `fri-live` validation CLI (149 frames @30.03 fps, 0 lost/dropped). BLOCKED on user: Research Studio side-by-side comparison at >=3 temperatures (docs/validation.md table). Disk ~2.9 GiB free — must be freed before Milestone 4 recording. Next dev: Milestone 3 live view (FastAPI + WebSocket + React) once validation table has at least one row. Next session: review probe_report.json, then implement camera/spinnaker.py and Milestone 2 validation.
