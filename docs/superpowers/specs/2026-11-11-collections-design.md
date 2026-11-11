# Collections: per-user / per-project folders for FLIR runs

Status: draft for Matt's approval (2026-11-11). Applies to version 0.4.62.

## Why

Until now Matt is the only person recording, but other people in the lab will start using the FLIR software, the lab Mac, and the shared FLIR SSD soon. The library today is one flat list: 92 runs on the SSD (`/Volumes/FLIR SSD/FLIR-recordings/`) and 1 on the Mac (`backend/experiments/`). Every user would see everyone's runs mixed together.

**Success:** someone sits down, picks themselves (or their project), sees only those runs, and records new runs straight into that folder.

## Goals

- **Collections.** A collection is a named folder for a person or a project. The list is flat, one level; Matt chose this over user→project nesting.
- **Location.** Collections live inside the FLIR data folders only:
  - Mac: `<experiments root>/<collection>/<run>/`
  - SSD: `/Volumes/FLIR SSD/FLIR-recordings/<collection>/<run>/`
  - Nothing is created at the SSD's top level. The SSD also holds `HEATR-data/`, `CT_SCANS/`, `vpi-runs/` and the lab-storage marker. FLIR never touches those. (Matt: "whatever this stuff is needs to be stored under the FLIR recordings, not in the same flat structure.")
- **The library shows one collection at a time.** A picker at the top of the Experiments page lists the collections and has "Add user or project". The run list, its counts and its sizes cover only the selected collection, both local and on the SSD, and also the offline cards when the SSD is unplugged.
- **New recordings go into the selected collection**, for both manual Record and armed/triggered starts. The record panel shows "Recording to: <collection>" before Record is pressed.
- **Moving a run between the Mac and the SSD keeps its collection.** For example, `mattmccoy/X` on the Mac becomes `FLIR-recordings/mattmccoy/X`, and the collection folder is created on the other side if it is missing.
- **Migration.** All existing runs (92 on the SSD and 1 local) move into `mattmccoy/`. Each move is a same-volume rename, so it is fast and safe.
  - Matt sees the exact list of runs, and confirms, before anything moves.
  - The offline drive index (`.drive-index.json`) is rewritten to match.
  - Runs can be recording, offloading or rendering at the moment of migration. Migration refuses to start while any of that is happening.

## Non-goals and anti-goals

- **Not access control.** Anyone can pick any collection, and there are no passwords. It is a filter for convenience.
- **Collections are flat.** No user→project nesting.
- **Not changing:** calibration, the record profile, presets, visible alignment, drive registration (`.storage.json`), the drive index file location, and `.rf_link.json`. These stay at the base data folder, shared by everyone. Note that `calibration_dir(root) = root.parent/"calibration"`, so the base root must not move.
- **TC-POWER integration unchanged.** It only uses the live endpoints and never refers to runs by name. One exception: the rf-link response includes the run's folder name; that stays as the basename.
- **Anti-goal: a run must never be lost, duplicated, or silently left out of the list.** If something is found that doesn't fit the layout, show it rather than hide it. Examples: a run still sitting loose at the top level, a collection folder that exists on only one side, two runs with the same name in different collections.

## Decisions

- **Selection is stored on the operator**, not per browser tab:
  - It lives in the base data folder, e.g. `.collection.json`, so recording and the library agree, and whoever walks up sees what is selected.
  - The selection is shown in the top bar.
  - Matt's call: recording follows the picker. Builder's call: the operator holds the state.
- **Collection names:**
  - Lowercase letters, digits, `-` and `_`, 1–40 characters (e.g. `mattmccoy`, `rf-sintering`).
  - Names that start with `.`, or that look like a run folder (`YYYYMMDD_HHMMSS_…`), are rejected.
  - Matt chose `mattmccoy` for his own runs.
- **Addressing runs:** a run is identified by collection plus run name. How that appears in API URLs is the builder's call: an explicit `{collection}` path segment or a query parameter, not a slash inside `{name}`.
  - Every place that keys state by bare run name must key by the pair (or by the run's path): derived/move/media/range jobs, render locks, smart ROI jobs, offline-index dedupe, frontend card ids, per-run browser storage scopes, and the open-run state.
- **Runs at the top level after migration** (e.g. a run copied in by hand): show them under a visible "Unsorted" entry in the picker, with a way to move them into a collection. Never drop them.

- **The last-used collection is remembered and reopens on load** (Matt's call, 2026-11-11: "remember the last one, but allow them to change collections"). Anyone can switch at any time, except while a recording or armed trigger is active (see below).

### Calls made by the designer (from the builder check) — Matt, check these

1. **Persisted keys are migrated, never orphaned.**
   - `.drive-index.json` entries gain a `collection` field (schema version bump). `offline_runs` dedupe and sort by (collection, name).
   - The frontend's per-run browser storage scopes (saved ROI edits, label positions, view state) are re-keyed from `name` to `collection/name` on first load after migration. Matt keeps all of his per-run state.
   - In-memory job records are not persisted, so they need no migration.
2. **The offline index keeps every collection.** Filtering happens on read. The picker lists collections that are known only from the index (SSD unplugged), marked "offline". You can browse them, but you cannot record into them until the SSD is back, because recording is local anyway.
3. **Recording always writes to the Mac**, to `<experiments root>/<collection>/`, as today, and creates the folder if it is missing. The SSD stays an offload target. Record (and Arm) is blocked, with a "pick a collection" prompt, when no collection is selected or "Unsorted" is selected. After migration the default is `mattmccoy`.
4. **One "operator busy" check** is true while any of these is running: a recording, an armed trigger, closed-loop control, a move/offload, or a derived/post-stop/media/smart-ROI job.
   - Migration refuses while it is true.
   - The collection picker is locked while a recording or armed trigger is active, so a live or pending run can never change folder.
5. **Name collisions are refused with a clear message, never silently.** This covers moving a run into a collection, or between the Mac and the SSD, when the destination already has that run name. There is no auto-suffix.
6. **Migration is two independent passes**, one per volume (Mac root, SSD `FLIR-recordings`).
   - Each pass has its own dry-run, confirm, and log file, written on that volume: `<base>/.collections-migration.log` and `FLIR-recordings/.collections-migration.log`.
   - Same-volume directory renames (including on the exFAT SSD) are atomic. The orphan AppleDouble `._<run>` files next to each run move with it, or are cleaned, following `storage._remove_tree`'s handling.
7. **Unexpected folders are shown, not hidden.** Directories directly inside a FLIR root that are neither a valid collection name nor a run show as "unexpected" in the picker and are never touched. There are none today.
8. **Storage totals on Setup stay global** (all users, both volumes) and are labelled as such. The Experiments page header counts only the selected collection.

## What's left to the builder

- **Exact UI:** the picker placement on the Experiments page, the add-collection dialog, and the top-bar indicator. Follow the existing tokens and theme; there must be no colour literals in `styles.css`.
- **Whether the selected collection also scopes:** the storage summary on Setup, `GET /api/experiments/summary`, and the free-space check. Free space is per volume, so it is unchanged.
- **The migration mechanism:** a one-time endpoint plus a UI confirm, or a script Matt runs. Either way it must:
  1. dry-run first, listing every source → destination;
  2. refuse while busy;
  3. be idempotent and resumable, so a re-run finishes a half-done migration;
  4. keep a log in the base folder.
- **Rename and delete of collections are out of scope for v1** unless trivial. Moving a single run to another collection is in scope, because "Unsorted" needs it.

## Constraints (house rules)

- **TDD.** Write the failing test first (red→green) for all logic. Fixtures must reflect real layouts, e.g. a captured `.drive-index.json` shape and a real run folder listing.
- **Real-data check before shipping.** Run the dry-run against the real SSD and the local root, read-only, and print what it would do.
- **Operator rules:**
  - Never restart or redeploy the lab operator without Matt's go.
  - Check that no recording, control, or post-stop/derived job is running before a restart.
  - Never run a bare `uv sync`; use `uv sync --extra dev --inexact`.
  - Never open the UI against the live :8000 operator; use a demo operator on another port.
- **Never touch the non-FLIR folders on the SSD.**
- Version bump in `__init__.py`, `pyproject.toml` and the `uv.lock` package entry. CI runs strict mypy, ruff and pytest, plus the frontend tests and tsc.
