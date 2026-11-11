# Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-user / per-project folders ("collections") for FLIR runs. The library shows one collection at a time, new recordings go into the selected collection, moves between the Mac and the SSD keep the collection, and existing runs migrate into `mattmccoy/`.

**Architecture:**
- A pure model module (`collections.py`) owns name rules, classification of what sits in a FLIR root, the run identity `RunRef(collection, name)`, and the operator-held selection (`<base>/.collection.json`).
- The API addresses a run by `{name}` plus a `collection` query parameter. Every handler resolves a run through one dependency, so mypy finds any call site that was missed. All in-memory job and lock keys use `RunRef.key` (`"<collection>/<name>"`, or `"<name>"` at the top level).
- Migration is a read-only planner plus an apply step that only uses `os.rename`, one pass per volume. The frontend carries a run as one string `RunKey` (`"<collection>/<name>"`). That makes every per-run browser scope `exp.<collection>/<name>` automatically. A one-time pass re-keys the old `exp.<name>` entries.

**Tech Stack:** Python 3.12 / FastAPI / lab-storage 0.1.0; React 18 + TypeScript (node --test, tsc).

**Spec:** `docs/superpowers/specs/2026-11-11-collections-design.md` (binding; read it, especially "Calls made by the designer").

**Decisions this plan makes where the spec leaves the call to the builder:**
- **Run addressing: query parameter `collection`, not a path segment.** The 44 `encodeURIComponent(name)` routes keep their shape, and so does the smart-ROI router.
  - Omitted `collection`: a *legacy lookup* by unique name across the top level and every collection, local then drive. Two matches → 409.
  - `collection=` (empty): the top level ("Unsorted").
  - `collection=<c>`: exactly that collection.
  - The frontend always sends it explicitly. Omitting it keeps the 187 existing test references and any old tab working during the transition.
- **`GET /api/experiments` and `/summary`** take the same parameter. When it is omitted, they list the operator's selected collection. With nothing selected, they list the top level, which is today's behaviour.
- **Unsorted representation.**
  - Selection value `""` = Unsorted, `null` = nothing selected.
  - `RunRef.collection` is `None` for the top level.
- **Migration mechanism.** A dry-run endpoint, then a confirm endpoint that carries the exact names Matt saw, then a Setup-page panel. AppleDouble `._<run>` orphans left after a rename are deleted, not moved. This matches `storage.move_experiment` (storage.py:351) and `lab_storage.fsutil.remove_tree`.
- **Browser-state re-keying** uses where each run lives *now* (`GET /api/collections/runs`), not the migration logs. A name found in more than one collection is left on its old key and reported. The planner never guesses.
- **Collection create** makes the local folder only, and is idempotent. The drive folder is created by the first move.
- **Offline-only collections** (known only from the index while the SSD is unplugged) can be browsed, but Record/Arm refuse them. This follows designer call 2 literally.

## Global Constraints

**Never touch these:**
- `127.0.0.1:8000`, launchd, `~/flir-research-interface`, or the real SSD (`/Volumes/FLIR SSD`). The only exception is the read-only dry-run in Task 12.
- The UI on `:8000`. For UI checks, run a demo operator on port `8765`, with a simulated camera and a scratch experiments root under the session scratchpad. Serve the built `frontend/dist` from that operator. Do not use `vite dev`: it proxies `/api` to `:8000` (frontend/vite.config.ts:27).
- The SSD's non-FLIR folders (`HEATR-data/`, `CT_SCANS/`, `vpi-runs/`, the lab-storage marker). Code only ever lists or renames inside `<mount>/FLIR-recordings/`.

**What stays where it is:**
- The base experiments root never moves: `calibration_dir(root) = root.parent/"calibration"` (analysis/calibration.py:20).
- These stay in the base root, shared: `.storage.json`, `.drive-index.json`, `.rf_link.json`, profile, alignment, presets.
- TC-POWER endpoints are unchanged. The rf-link response keeps the run folder basename.

**Collection names:**
- Must match `^[a-z0-9_-]{1,40}$`.
- Rejected when they start with `.` or match `^\d{8}_\d{6}(_|$)`.

**Data safety:**
- No run is ever overwritten, auto-suffixed or silently dropped. A collision is refused with a message naming the destination.
- Same-volume moves use `os.rename` only, never `shutil.move`. A cross-device move must fail, not copy.

**Fixtures** are captured or derived from real data:
- `tests/fixtures/drive_index_v1_20261109.json` is captured from the real `.drive-index.json`, with redaction.
- `tests/fixtures/flir_recordings_listing_20261111.json` is the 92 real run names, taken from that index.
- Every test that uses a hand-made shape says so in a comment.

**Tooling:**
- Never run a bare `uv sync`; use `cd backend && uv sync --extra dev --inexact`.
- Never commit `backend/.venv` or the `frontend/node_modules` symlink. The `node_modules/` gitignore pattern does not match a symlink, so stage explicit paths only. Never use `git add -A` or `git add .`.

**Every task:**
- Red→green TDD.
- Backend gate: `backend/.venv/bin/python -m pytest -q`, `backend/.venv/bin/ruff check .`, `backend/.venv/bin/mypy flir_research_interface` (run from `backend/`).
- Frontend gate: `node --experimental-strip-types --test 'src/**/*.test.ts'` and `npx tsc --noEmit` (run from `frontend/`).
- No colour literals in `styles.css`; use theme tokens (`lib/theme.test.ts` enforces it).

**Release:** the version bump to `0.4.63` happens only in Task 12, in `backend/flir_research_interface/__init__.py`, `backend/pyproject.toml`, and the `flir-research-interface` package entry in `backend/uv.lock`. No restart or redeploy of the lab operator without Matt's go.

## Review Focus

1. **A run hidden or lost.**
   - Cases: a run left at a root's top level after migration; a collection folder on only one side; a folder that is neither a collection nor a run.
   - Expected: each appears, as "Unsorted", as a collection with `local`/`drive` flags, or as "unexpected". Nothing is moved or deleted.
   - Tests: `test_collections_doc_shows_everything` (Task 2), `test_unsorted_listing_excludes_collection_folders` (Task 2).
2. **Same run name in two places.**
   - Cases: moving to the SSD when `FLIR-recordings/<c>/<name>` already exists (including a case-only difference on exFAT); moving into a collection that already has the name; two collections holding the same name and both having jobs.
   - Expected: 409 naming the destination, and both copies untouched. Job status never crosses between collections.
   - Tests: `test_move_to_drive_refuses_existing_name`, `test_move_refuses_casefold_clash`, `test_move_into_collection_refuses_clash` (Task 6); `test_jobs_are_keyed_per_collection` (Task 3).
3. **The drive index after migration and after scoped listings.**
   - Cases: a v1 index with no `collection` field; listing one collection while the SSD is connected; the SSD pass of the migration.
   - Expected: v1 entries read as top level, and a scoped refresh replaces only that collection's entries. After the SSD pass, entries carry `collection` and rewritten `path` / `thermal_preview.path`.
   - Tests: `test_v1_index_reads_as_top_level`, `test_remember_one_collection_keeps_others` (Task 7); `test_drive_pass_rewrites_index` (Task 8).
4. **Recording into the wrong collection.**
   - Cases: changing the picker while armed or recording; the trigger firing after the picker could have changed; nothing or Unsorted selected; an offline-only collection selected.
   - Expected: the picker change is refused while recording or armed. An armed start writes to the arm-time collection. Record/Arm return 409 with "pick a collection before recording".
   - Tests: `test_picker_locked_while_armed_and_recording`, `test_armed_start_uses_arm_time_collection`, `test_record_refuses_without_collection` (Task 5); `test_record_refuses_offline_only_collection` (Task 7).
5. **Stale per-run browser state.**
   - Case: ROI edits, masks, label nudges and smart-view prefs saved under `exp.<name>` before migration.
   - Expected: they move to `exp.<collection>/<name>` once, never overwrite a newer key, and stay put when the name is ambiguous. Re-running is a no-op.
   - Tests: `migrates every key family`, `never overwrites an existing new key`, `leaves ambiguous names`, `is idempotent` (Task 9).

---

### Task 1: Environment, collection model and selection store

**Files:**
- Create: `backend/flir_research_interface/collections.py`
- Create: `backend/tests/test_collections.py`
- Create: `backend/tests/fixtures/drive_index_v1_20261109.json`, `backend/tests/fixtures/flir_recordings_listing_20261111.json`

**Interfaces:**
- Produces (all in `flir_research_interface.collections`):
  - Constants:
    - `SELECTION_FILE = ".collection.json"`
    - `NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}$")`
    - `RUN_LIKE_RE = re.compile(r"^\d{8}_\d{6}(_|$)")`
  - `collection_name_error(name: str) -> str | None` returns `None` when the name is valid, otherwise a user-facing reason.
  - `run_name_error(name: str) -> str | None` rejects `""`, `"."`, `".."`, `/` and `\`, the same rule as `_exp_dir` today (app.py:1447).
  - `@dataclass(frozen=True) class RunRef: collection: str | None; name: str`, where `None` means the top level.
    - property `key -> str`: `"c/name"` or `"name"`.
    - `rel() -> Path`.
    - `classmethod from_dir(run_dir: Path, roots: Sequence[Path]) -> RunRef`: the parent is one of `roots` (resolved) → top level, otherwise the parent's name.
  - `EntryKind = Literal["run", "collection", "unexpected", "skip"]`.
  - `classify_entry(path: Path) -> EntryKind`:
    - `skip` for a name that `lab_storage.fsutil.listable` rejects, a name that starts with `.`, and non-directories;
    - `run` if `RUN_LIKE_RE` matches or `metadata.json` exists;
    - `collection` if `collection_name_error` is `None`;
    - otherwise `unexpected`.
  - `@dataclass(frozen=True) class RootScan: collections: tuple[str, ...]; runs: tuple[str, ...]; unexpected: tuple[str, ...]`, each sorted.
  - `scan_root(root: Path) -> RootScan` returns an empty scan for a missing root.
  - `load_selection(base: Path) -> str | None` returns a valid name, `""` (Unsorted) or `None`. A missing, malformed or invalid-name file gives `None`.
  - `save_selection(base: Path, selected: str | None) -> None` writes `{"selected": ...}` atomically and creates `base` if needed. It raises `ValueError` for an invalid name.

- [ ] **Step 1: Set up the worktree (no commit).**
  - Run: `cd backend && uv sync --extra dev --inexact` and `ln -s "/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR/frontend/node_modules" frontend/node_modules`.
  - Then run the backend gate and the frontend gate once.
  - Expected: all green at v0.4.62.
  - `git status --porcelain` must show neither `.venv` nor `node_modules`. If the symlink shows up, never stage it.
- [ ] **Step 2: Capture the fixtures (read-only, from the Mac-side index, never the SSD).**
  - Source: `"/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR/backend/experiments/.drive-index.json"`.
  - `drive_index_v1_20261109.json`: keep `label` and `last_seen_utc`, and the first 3 `runs` with **every key kept**. Replace the values of `manifest`, `experiment`, `metadata`, `visible`, `rois`, `previews` and `visible_alignment` with `{}` / `[]` / `null` of the same JSON type. Keep `path` and `thermal_preview.path` verbatim (absolute `/Volumes/FLIR SSD/FLIR-recordings/<run>` strings).
  - `flir_recordings_listing_20261111.json`: `{"source": "names from .drive-index.json 2026-11-09", "runs": [92 names]}`.
  - Check: `grep -i serial` on both files prints nothing.
- [ ] **Step 3: Write the failing tests** in `backend/tests/test_collections.py`:

```python
@pytest.mark.parametrize("ok", ["mattmccoy", "rf-sintering", "a", "x_1", "a" * 40])
def test_valid_collection_names(ok: str) -> None:
    assert collection_name_error(ok) is None

@pytest.mark.parametrize("bad", ["", "a" * 41, "Matt", "has space", ".hidden", "a/b",
                                 "20261102_165506_Run", "20261102_165506", "FLIR-recordings"])
def test_rejected_collection_names(bad: str) -> None:
    assert collection_name_error(bad)

def test_run_ref_key_and_from_dir(tmp_path: Path) -> None:
    assert RunRef("mattmccoy", "r").key == "mattmccoy/r" and RunRef(None, "r").key == "r"
    assert RunRef.from_dir(tmp_path / "mattmccoy" / "r", [tmp_path]) == RunRef("mattmccoy", "r")
    assert RunRef.from_dir(tmp_path / "r", [tmp_path]) == RunRef(None, "r")

def test_scan_real_ssd_shape(tmp_path: Path) -> None:
    # dirs: the 92 real run names (fixture); siblings "._<run>" for 90 of them (count from the
    # 2026-11-11 recon; which 90 is synthesised), plus .Trashes, a lab-storage staging dir,
    # one collection and one unexpected folder (hand-made)
    ...
    scan = scan_root(tmp_path)
    assert len(scan.runs) == 92 and scan.collections == ("mattmccoy",)
    assert scan.unexpected == ("Old Stuff",)

def test_selection_roundtrip_and_malformed(tmp_path: Path) -> None:
    assert load_selection(tmp_path) is None
    save_selection(tmp_path, "mattmccoy"); assert load_selection(tmp_path) == "mattmccoy"
    save_selection(tmp_path, ""); assert load_selection(tmp_path) == ""
    (tmp_path / ".collection.json").write_text("{nope"); assert load_selection(tmp_path) is None
    with pytest.raises(ValueError): save_selection(tmp_path, "Bad Name")
```

- [ ] **Step 4: Run** `backend/.venv/bin/python -m pytest tests/test_collections.py -q`. Expected: FAIL (`ModuleNotFoundError: flir_research_interface.collections`).
- [ ] **Step 5: Implement** `collections.py`. Use `storage._atomic_json` for the write, and export the public names in `__all__`.
- [ ] **Step 6: Run** the same test, expecting PASS. Then run the full backend gate: clean.
- [ ] **Step 7: Commit** `feat(collections): collection model, name rules and selection store` (explicit paths: the module, the test, the two fixtures).

### Task 2: Collections API and per-collection listing

**Files:**
- Create: `backend/flir_research_interface/api/collections_routes.py`
- Create: `backend/tests/test_api_collections.py`
- Modify: `backend/flir_research_interface/playback/reader.py:177` (`list_experiments`)
- Modify: `backend/flir_research_interface/api/app.py:1408-1444` (`experiments`, `experiments_summary`)

**Interfaces:**
- Consumes: Task 1 (`scan_root`, `load_selection`, `save_selection`, `collection_name_error`).
- Produces:
  - `list_experiments(root: Path, library: str = "local", *, names: Collection[str] | None = None)`. `names=None` keeps today's behaviour; otherwise only those child dirs are listed.
  - `register_collections_routes(app: FastAPI, roots: Callable[[], list[tuple[str, Path]]]) -> None`, with these routes:
    - `GET /api/collections` returns the `CollectionsDoc` below.
    - `POST /api/collections {name}` validates (400 with the reason), makes `<base>/<name>/` locally (idempotent), and returns the doc.
    - `PUT /api/collections/selected {name: str | null}` validates: 400 for an invalid name; 404 for a name that is not `""` and is not in the doc. It saves and returns the doc. The lock is added in Task 5.
  - `CollectionsDoc` JSON:
    `{"selected": str|null, "collections": [{"name", "local": bool, "drive": bool, "offline": bool}], "unsorted": {"local": int, "drive": int}, "unexpected": [{"library", "name"}], "drive_connected": bool}`. `offline` is always `false` until Task 7.
  - Every listing item gains `"collection": str | null`.
  - `GET /api/experiments?collection=` and `/summary?collection=`:
    - parameter omitted → the selected collection;
    - nothing selected, or `""` → the top level, filtered to `scan.runs`;
    - a name → `<root>/<name>` in each root.
    - An invalid name → 400.

- [ ] **Step 1: Write failing tests** (`TestClient(create_app(default_backend="simulated", experiments_root=tmp, min_free_gb=0.0))`; runs made with `mkdir` + `metadata.json`, hand-made shape, with a comment saying so):
  - `test_collections_doc_shows_everything`:
    - local has `mattmccoy/`, a top-level run and `Old Stuff/`; drive has `rf-sintering/` (register a drive at `tmp/Drive`).
    - `collections == [{"name":"mattmccoy","local":True,"drive":False,...},{"name":"rf-sintering","local":False,"drive":True,...}]`;
    - `unsorted == {"local":1,"drive":0}`;
    - `{"library":"local","name":"Old Stuff"} in unexpected`.
  - `test_add_collection_validates_and_is_idempotent`: `"Bad Name"` → 400; `"rf-sintering"` twice → 200 both times, folder exists.
  - `test_select_persists_on_operator`: PUT `mattmccoy` → `.collection.json` holds it, and a fresh app over the same root reports `selected == "mattmccoy"`. PUT `"nope"` → 404.
  - `test_listing_scoped_to_collection`: one run in `mattmccoy/` and one at the top level. `?collection=mattmccoy` lists exactly the first with `collection == "mattmccoy"`. Omitting the parameter after selecting `mattmccoy` gives the same.
  - `test_unsorted_listing_excludes_collection_folders`: `?collection=` lists the top-level run only. No card for `mattmccoy` or `Old Stuff`.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_api_collections.py -q`. Expected: FAIL (404 on `/api/collections`; collection folders show up as unreadable cards).
- [ ] **Step 3: Implement** the `names=` filter, `collections_routes.py`, and the scoped listing/summary. Register the routes in `create_app` next to `register_smart_roi_routes`. The listing's existing `remember_drive_runs` / `offline_runs` calls stay as they are in this task. Task 7 scopes them; until then a connected-drive listing of one collection can shrink the index. That is acceptable only because Task 7 follows directly and no data is moved before Task 8.
- [ ] **Step 4: Run** the new tests, expecting PASS. Run the full backend gate: green. The existing listing tests still pass, because nothing is selected and the top level lists as before.
- [ ] **Step 5: Commit** `feat(collections): collections API and per-collection listing`.

### Task 3: Run addressing by collection and run-keyed jobs and locks

**Files:**
- Modify: `backend/flir_research_interface/api/app.py`: `_exp_dir` (1446), `_exp_dir_in` (1569), `_open`, every `/api/experiments/{name}...` handler, the job dicts (526-529) and their `.get(name)` / `[name] =` sites, `render_locks.get(...)` (550, 1551, 1808, 1875, 1928), and `_schedule_post_stop_exports`.
- Modify: `backend/flir_research_interface/api/smart_roi_routes.py` (`register_smart_roi_routes`, `compute_stored_smart_rois`)
- Create: `backend/tests/test_api_run_addressing.py`

**Interfaces:**
- Consumes: `RunRef`, `run_name_error`, `collection_name_error`, `scan_root` (Task 1); `_roots()` (app.py:1400).
- Produces (inside `create_app`):
  - `@dataclass(frozen=True) class RunQuery: name: str; collection: str | None`, where `None` means the parameter was omitted. It lives in `collections.py` so that `smart_roi_routes` can import it.
  - `run_query(name: str, collection: str | None = None) -> RunQuery` is a FastAPI dependency; both values are validated with 400. `RunDep = Annotated[RunQuery, Depends(run_query)]`.
  - `_resolve(q: RunQuery, library: str | None = None) -> tuple[RunRef, Path]` behaves as follows:
    - explicit collection → `root/<c or "">/name`, local first;
    - omitted → the legacy unique lookup over the top level and every `scan_root(root).collections` in every root;
    - two or more distinct `RunRef`s → 409 `"<name> exists in more than one collection (<a>, <b>); pass ?collection="`;
    - nothing found → 404.
    - `_exp_dir(q) -> Path` and `_exp_dir_in(q, library) -> Path` wrap it. The old string signatures are removed, so mypy flags every unconverted site.
  - `_job_key(q: RunQuery) -> str` gives `RunRef(c or None, name).key` when the collection is explicit; otherwise `_resolve(q)[0].key`, falling back to `q.name` on 404.
  - Job dicts and `render_locks` are keyed by `RunRef.key`. `smart_jobs` is keyed by `(RunRef.key, roi_id)`. Post-stop exports and `compute_stored_smart_rois` derive the key with `RunRef.from_dir(exp_dir, [r for _, r in _roots()])`.
  - `register_smart_roi_routes(app, resolve: Callable[[RunQuery], Path], job_key: Callable[[RunQuery], str])`, and `compute_stored_smart_rois(app, exp_dir, *, key: str, only_missing_or_stale: bool = False)`.

- [ ] **Step 1: Write failing tests** (two hand-made runs named `20261102_165506_Run`, one in `mattmccoy/` and one in `rf-sintering/`, each with a distinct `metadata.json`; a real readable run is made by recording with the simulated camera where a handler needs a reader):
  - `test_explicit_collection_resolves_each_copy`: `GET /api/experiments/20261102_165506_Run/reveal?collection=mattmccoy` and `?collection=rf-sintering` hit different folders. Use a `reveal_runner` stub that records the path.
  - `test_omitted_collection_is_unique_lookup`: with one copy → 200; with both → 409 whose detail names both collections.
  - `test_empty_collection_means_top_level`: a top-level run resolves with `?collection=` and 404s with `?collection=mattmccoy`.
  - `test_invalid_collection_param_400`: `?collection=Bad%20Name` → 400.
  - `test_jobs_are_keyed_per_collection`: seed `app.state.derived_jobs["mattmccoy/20261102_165506_Run"] = {"state": "running"}`. Then `GET .../export/derived/status?collection=rf-sintering` → `{"state":"idle"}`, and `?collection=mattmccoy` → running.
  - `test_post_stop_lock_key_includes_collection`: `RunRef.from_dir(root/"mattmccoy"/"r", [root]).key == "mattmccoy/r"`. This is a unit test on the function the scheduler calls.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_api_run_addressing.py -q`. Expected: FAIL (the `collection` parameter is ignored → wrong folder or 404).
- [ ] **Step 3: Implement.** Convert each `name: str` path handler to `run: RunDep` and use `run.name` where the bare name is still needed (filenames, messages). Leave `presets/{name}` alone; it is not a run.
- [ ] **Step 4: Run** the new tests: PASS. Run the full backend gate. All 187 existing `/api/experiments/{name}` test references pass unchanged through the legacy lookup. mypy is clean, which proves no handler still calls the old `_exp_dir(str)`.
- [ ] **Step 5: Commit** `feat(collections): address runs by collection; key jobs and locks by run`.

### Task 4: One "operator busy" predicate

**Files:**
- Create: `backend/flir_research_interface/busy.py`, `backend/tests/test_busy.py`
- Modify: `backend/flir_research_interface/api/app.py` (`_busy_inputs`, route)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class BusyInputs: recording: bool; finalizing: bool; armed: bool; control_engaged: bool; running_jobs: tuple[str, ...]; background_tasks: int`
  - `busy_reasons(i: BusyInputs) -> list[str]`, in this fixed order:
    - `"recording"`
    - `"finishing a recording"`
    - `"armed trigger"`
    - `"closed-loop control engaged"`
    - then each `running_jobs` entry
    - then `f"{n} background task(s)"` when `background_tasks > 0`
  - In app: `_busy() -> list[str]` builds `BusyInputs` from:
    - `recorder().state == RECORDING`
    - `bool(app.state.finalizing)`
    - `app.state.armer is not None`
    - `rf_engaged(app.state.control_last, app.state.rf_link_last_event, now)` (rf_status.py:29)
    - every job dict entry with `state == "running"` as `f"{kind} {key}"`, for kind ∈ move/derived/media/range/smart
    - `len(app.state.render_tasks)`, which covers the post-stop exports scheduled at app.py:543 and every job task
  - `GET /api/operator/busy` → `{"busy": bool, "reasons": [...]}`.

- [ ] **Step 1: Write failing tests:**
  - `test_idle_is_not_busy`: all false/empty → `[]`.
  - `test_each_signal_reports`: parametrize over each field → its exact string.
  - `test_post_stop_exports_count_as_busy` (API): record and stop a simulated run, then poll `/api/operator/busy` immediately. It must report `"1 background task(s)"` or more until the post-stop task ends, then `{"busy": false}`.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_busy.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `busy.py`, `_busy`, and the route.
- [ ] **Step 4: Run** the tests: PASS. Run the full backend gate: green.
- [ ] **Step 5: Commit** `feat(operator): single busy predicate covering recording, arm, control and jobs`.

### Task 5: Recording into the selected collection; Record/Arm block; picker lock

**Files:**
- Modify: `backend/flir_research_interface/api/app.py`:
  - `_start_recording` (1141): `Recorder(..., experiments_root=root / collection)`
  - `recording_start` (1196) and the arm route (1278); the armed loop (1215-1240) reads `app.state.arm_collection`
  - `recording_status` (1360) adds `"collection"`
- Modify: `backend/flir_research_interface/api/collections_routes.py` (PUT selected → lock)
- Create: `backend/tests/test_api_record_collection.py`, `backend/tests/collection_helpers.py`
- Modify: the 24 test files that call `/api/recording/start` or `/api/recording/arm` (list them with `grep -ln "recording/start\|recording/arm" backend/tests/*.py`)

**Interfaces:**
- Consumes: `load_selection` (Task 1); the doc from Task 2.
- Produces:
  - `_recording_collection() -> str` raises `HTTPException(409, "pick a collection before recording")` when the selection is `None` or `""`.
  - `_start_recording(req, *, collection: str, attach_service=..., nuc_first=...)`.
  - The arm route stores `app.state.arm_collection: str | None` at arm time. Disarm and a finished arm clear it.
  - PUT selected → 409 `"the collection can't change while a recording or armed trigger is active"` while recording or armed.
  - `tests/collection_helpers.py`: `select_collection(c: TestClient, name: str = "t") -> None` (POST then PUT).

- [ ] **Step 1: Write failing tests:**
  - `test_record_refuses_without_collection`: start with nothing selected → 409 with that exact detail. Select Unsorted (`""`) → also 409. Same for arm.
  - `test_record_writes_into_collection`: select `rf-sintering` → `experiment_dir` parent is `root/"rf-sintering"`. The folder is created if missing.
  - `test_picker_locked_while_armed_and_recording`: while recording, PUT selected → 409. After stop → 200. Same for arm and disarm.
  - `test_armed_start_uses_arm_time_collection`: arm with `mattmccoy` selected. Then write `.collection.json` = `other` directly (simulating a bypass of the lock) and fire the trigger as in `tests/test_arm.py`. The run lands in `mattmccoy/`.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_api_record_collection.py -q`. Expected: FAIL (a 200 instead of 409; the run lands at the top level).
- [ ] **Step 3: Implement** the block, the collection root, `arm_collection`, and the lock.
- [ ] **Step 4: Update the 24 recording test files.** Call `select_collection(c)` right after connecting. Any assertion on `root / name` becomes `root / "t" / name`. Paths taken from `experiment_dir` need no change.
- [ ] **Step 5: Run** the new tests and then the full backend gate. All green.
- [ ] **Step 6: Commit** `feat(collections): record and arm into the selected collection; lock the picker while live`.

Note: from this task until Task 10 lands, the UI cannot record unless a collection was selected through the API. That is acceptable because nothing is deployed until Task 12.

### Task 6: Moves keep the collection; collisions refused; move into a collection

**Files:**
- Modify: `backend/flir_research_interface/storage.py` (add `destination_clash`, `move_into_collection`, `CollectionClashError`)
- Modify: `backend/flir_research_interface/api/app.py`: the move route (1507-1563); new route `POST /api/experiments/{name}/collection`
- Create: `backend/tests/test_collection_moves.py`

**Interfaces:**
- Consumes: `RunDep`, `_resolve`, `_job_key` (Task 3); `collection_name_error` (Task 1).
- Produces:
  - `storage.destination_clash(dst_parent: Path, name: str) -> str | None` returns the clashing entry when `dst_parent/name` exists or `lab_storage.fsutil.casefold_collision(dst_parent, name)` finds one.
  - `class CollectionClashError(ValueError)`.
  - `storage.move_into_collection(run_dir: Path, root: Path, collection: str | None) -> Path`:
    - `os.rename` to `root/<collection or "">/run_dir.name`, creating the collection dir;
    - raises `CollectionClashError` on a clash;
    - unlinks an orphan `run_dir.parent/"._"+name` afterwards.
  - Move route: the destination is `dst_root / ref.collection` (top-level runs stay top level). A clash → 409 `"<dest> already has a run named <name>; nothing was moved"`, where `<dest>` is `"<collection> on the drive"` / `"<collection> on this Mac"`. The check runs before the job starts.
  - `POST /api/experiments/{name}/collection?collection=<src>` with body `{"to": str, "library": "local"|"drive"|null}` (`to: ""` = Unsorted):
    - 400 for an invalid name;
    - 409 if this run is recording, or its `render_locks` entry is `locked()`, or a move/derived/media/range job for its key is running;
    - 409 on a clash;
    - otherwise returns `{"collection": to or null, "name": name}`.

- [ ] **Step 1: Write failing tests:**
  - `test_move_to_drive_keeps_collection`: record into `mattmccoy` (simulated), register `tmp/Drive`, move to the drive. The run is at `Drive/FLIR-recordings/mattmccoy/<run>` and `mattmccoy/` was created there. Restore puts it back at `local/mattmccoy/<run>`.
  - `test_move_to_drive_refuses_existing_name`: pre-create `Drive/FLIR-recordings/mattmccoy/<run>/` → 409 with the exact message. Both folders are unchanged (compare file listings).
  - `test_move_refuses_casefold_clash`: pre-create `.../mattmccoy/<RUN uppercased>` → 409. This is a hand-made shape that mimics exFAT case-insensitivity.
  - `test_move_into_collection_from_unsorted`: a top-level run plus a `._<run>` sibling. POST `{"to":"mattmccoy"}` with `?collection=` → it now lives at `mattmccoy/<run>` and the sibling is gone.
  - `test_move_into_collection_refuses_clash`: the target already has the name → 409; the source is still at the top level.
  - `test_move_into_collection_refuses_busy_run`: hold `render_locks.get(key)` in the test → 409.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_collection_moves.py -q`. Expected: FAIL (the run lands at `FLIR-recordings/<run>`; 404 on `/collection`).
- [ ] **Step 3: Implement** the storage helpers and both routes.
- [ ] **Step 4: Run** the new tests and the full backend gate (including `tests/test_storage.py` and `tests/test_storage_api.py`): green.
- [ ] **Step 5: Commit** `feat(collections): moves keep the collection; refuse name clashes; move a run into a collection`.

### Task 7: Drive index v2 and offline runs per collection

**Files:**
- Modify: `backend/flir_research_interface/storage.py` (`remember_drive_runs` 222, `offline_runs` 236; add `offline_collections`, `INDEX_SCHEMA = 2`)
- Modify: `backend/flir_research_interface/api/app.py` (listing at 1420-1427), `api/collections_routes.py` (`offline` flag), `_recording_collection` (Task 5)
- Create: `backend/tests/test_drive_index_v2.py`

**Interfaces:**
- Produces:
  - Index file shape: `{"schema": 2, "label", "last_seen_utc", "runs": [{..., "collection": str|null}]}`. A file without `schema` is v1, and its runs read as `collection: null`.
  - `remember_drive_runs(local_root, items, label, *, collection: str | None) -> None` replaces only the entries whose `collection` equals `collection` and keeps every other entry. It rewrites only on change, sorts by `(collection or "", name)`, and always writes `schema: 2`.
  - `offline_runs(local_root, *, collection: str | None) -> list[dict]` returns only that collection, marked as today (`library: "offline"`).
  - `offline_collections(local_root) -> set[str]`.
  - The listing passes the listed collection to both calls and dedupes offline cards by `(collection, name)`.
  - In `CollectionsDoc`, a collection known only from the index while the drive is unplugged appears with `offline: true`.
  - `_recording_collection()` refuses an offline-only selection: `"collection '<c>' is only on the unplugged drive; plug it in or pick another collection"`. An offline-only collection means it is not a local folder and the drive is not connected.

- [ ] **Step 1: Write failing tests**, using `tests/fixtures/drive_index_v1_20261109.json` copied into `tmp/local/.drive-index.json`:
  - `test_v1_index_reads_as_top_level`: `offline_runs(local, collection=None)` returns the 3 captured runs. `offline_runs(local, collection="mattmccoy") == []`.
  - `test_remember_one_collection_keeps_others`: remember 1 run for `mattmccoy`. The file has `schema == 2`, the 3 v1 runs with `collection: None`, and 1 `mattmccoy` run. Remembering `[]` for `mattmccoy` removes only that run.
  - `test_offline_collection_listed_and_browsable` (API): index entries with `collection: "rf-sintering"`, drive registered but its folder deleted (unplugged). `/api/collections` has `{"name":"rf-sintering","offline":True,...}`, and `/api/experiments?collection=rf-sintering` returns those cards with `offline: true`.
  - `test_record_refuses_offline_only_collection`: select `rf-sintering` in that state → `recording/start` 409 with the exact message.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_drive_index_v2.py -q`. Expected: FAIL (`unexpected keyword argument 'collection'`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests and the full backend gate: green.
- [ ] **Step 5: Commit** `feat(storage): drive index v2 keeps every collection; offline cards per collection`.

### Task 8: Migration API (dry-run, confirm, log, idempotent, per volume)

**Files:**
- Create: `backend/flir_research_interface/collections_migration.py`, `backend/tests/test_collections_migration.py`
- Modify: `backend/flir_research_interface/storage.py` (add `reindex_collection`)
- Modify: `backend/flir_research_interface/api/collections_routes.py` (migration routes; `register_collections_routes` gains `busy: Callable[[], list[str]]`)

**Interfaces:**
- Consumes: `scan_root`, `classify_entry`, `collection_name_error`, `save_selection`, `load_selection` (Task 1); `_busy` (Task 4); `storage.connected_drive`.
- Produces:
  - `LOG_NAME = ".collections-migration.log"`.
  - `@dataclass(frozen=True) class MigrationMove: name: str; src: Path; dst: Path`.
  - `@dataclass(frozen=True) class MigrationPlan: base: Path; target: str; moves: tuple[MigrationMove, ...]; conflicts: tuple[tuple[str, str], ...]; appledouble: int; unexpected: tuple[str, ...]; already_in_target: int`.
  - `plan_migration(base: Path, target: str) -> MigrationPlan` is **read-only**:
    - every `scan_root(base).runs` entry becomes a move to `base/target/name`;
    - an existing destination (or a casefold clash) goes into `conflicts` and is never moved;
    - `appledouble` counts the `._<run>` siblings of the planned moves;
    - `already_in_target` is the number of runs already under `base/target`.
  - `@dataclass(frozen=True) class MigrationResult: moved: tuple[MigrationMove, ...]; failed: tuple[tuple[str, str], ...]; skipped: tuple[str, ...]; log: Path`.
  - `apply_migration(plan: MigrationPlan, *, confirm: Collection[str], log_path: Path) -> MigrationResult`:
    - moves only the names in `confirm` that are still valid at apply time (the source exists and the destination does not), with `os.rename`;
    - deletes the orphan `._<name>` afterwards;
    - appends one JSON line per event (`{"ts","event":"start"|"move"|"error"|"done","name","src","dst","error"?}`) to `log_path`, flushing every line;
    - continues past a failure.
  - `storage.reindex_collection(local_root: Path, moved: Iterable[str], collection: str, drive_root: Path) -> int`:
    - for v1/v2 entries with `collection is None` and a name in `moved`, sets `collection` and rewrites `path` and `thermal_preview.path`, replacing the prefix `drive_root/name` with `drive_root/collection/name`;
    - writes `schema: 2` and returns the count.
  - Routes:
    - `GET /api/collections/migration?volume=local|drive&target=mattmccoy` returns `{"volume","base","target","moves":[{"name","src","dst"}],"conflicts":[{"name","reason"}],"appledouble","unexpected","already_in_target","busy":[...]}`. It returns 409 for `drive` when no drive is connected.
    - `POST /api/collections/migration` takes `{"volume","target","confirm":[names]}`:
      - 409 `"operator is busy: <reasons>; migration not started"` when `_busy()` is non-empty;
      - 400 for an invalid target or an empty `confirm`;
      - it re-plans, applies, and logs to `<base>/.collections-migration.log`; for `drive` it then runs `reindex_collection`;
      - for `local` with no selection it sets `selected = target`;
      - it returns `{"moved":[names],"failed":[{"name","error"}],"skipped":[names],"log":str}`.

- [ ] **Step 1: Write failing tests.** The base is built from the 92 real names in `flir_recordings_listing_20261111.json`, each a dir with `metadata.json`, plus 90 `._<run>` siblings. Synthetic, per the recon counts.
  - `test_plan_is_read_only_and_complete`: snapshot `sorted(os.walk(base))` and every mtime → `plan_migration(base, "mattmccoy")` → snapshot equal. `len(plan.moves) == 92`, `plan.appledouble == 90`, and `plan.conflicts == ()`.
  - `test_apply_moves_confirmed_only_and_logs`: confirm 10 names → those 10 under `mattmccoy/`, 82 still at the top level. The log has `start`, 10 `move` and `done` lines. No `._` sibling remains for the 10.
  - `test_rerun_finishes_half_done_migration`: after the partial apply, a new plan has 82 moves and `already_in_target == 10`. Applying all of them leaves 0 runs at the top level.
  - `test_conflict_never_overwrites`: a pre-existing `mattmccoy/<name>` with different content → it is in `conflicts`, absent from `moves`, and both copies are byte-identical before and after.
  - `test_unexpected_and_collections_untouched`: `Old Stuff/` and `rf-sintering/` are not in `moves`, and `Old Stuff` is in `unexpected`.
  - `test_cross_device_rename_fails_not_copies`: monkeypatch `os.rename` to raise `OSError(errno.EXDEV)` → the entry is in `failed`, and the source is intact.
  - `test_drive_pass_rewrites_index` (API): drive = `tmp/Drive`, with `FLIR-recordings` holding the fixture's 3 run names and `.drive-index.json` = the captured v1 fixture with its paths rebased onto `tmp/Drive` (stated in the test). POST drive migration → the index has `schema: 2`, every entry has `collection: "mattmccoy"`, and `path` ends with `/FLIR-recordings/mattmccoy/<name>`, as does `thermal_preview.path` where present.
  - `test_migration_refuses_while_busy` (API): seed `move_jobs["x"] = {"state":"running"}` → POST 409 with the message prefix; nothing moved.
  - `test_local_migration_selects_target`: with nothing selected, a local migration → `selected == "mattmccoy"`.
- [ ] **Step 2: Run** `backend/.venv/bin/python -m pytest tests/test_collections_migration.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module, `reindex_collection`, and the routes.
- [ ] **Step 4: Run** the new tests and the full backend gate: green.
- [ ] **Step 5: Commit** `feat(collections): per-volume migration with dry-run, confirm, log and index rewrite`.

### Task 9: Frontend run keys, collection-aware API calls, browser-state re-keying

**Files:**
- Create: `frontend/src/lib/runKey.ts`, `frontend/src/lib/runKey.test.ts`, `frontend/src/lib/scopeMigration.ts`, `frontend/src/lib/scopeMigration.test.ts`
- Modify:
  - `frontend/src/lib/api.ts`: every `/api/experiments/${encodeURIComponent(name)}…` route (44 hits, minus the 2 `presets` routes) → `runPath(name, "…")`; `experiments(collection)`; `Experiment.collection`; new calls.
  - `frontend/src/lib/layout.ts` (action `renameSmartViewScopes`).
  - `frontend/src/App.tsx` (`openExp` holds a RunKey; the crumb shows `runName`; a re-key effect on load).
  - `frontend/src/components/ExperimentsPage.tsx` (`cardId`, all `api.*(e.name…)` → `keyOf(e)`).
  - `frontend/src/components/ExperimentCard.tsx:27` (`scope = \`exp.${keyOf(exp)}\``).
  - `frontend/src/components/PlaybackPage.tsx`: `p.name` is a RunKey; use `runName(p.name)` wherever it is shown or used in a filename.
- Modify (backend): `api/collections_routes.py` adds `GET /api/collections/runs`; test in `backend/tests/test_api_collections.py`.

**Interfaces:**
- Consumes: the listing `collection` field (Task 2); offline `collection` (Task 7).
- Produces:
  - `type RunKey = string`.
  - `runKey(collection: string | null | undefined, name: string): RunKey`.
  - `parseRunKey(k: RunKey): { collection: string | null; name: string }`.
  - `runName(k)`.
  - `keyOf(e: { collection?: string | null; name: string }): RunKey`.
  - `runPath(k: RunKey, suffix = ""): string` appends `?collection=` or `&collection=` (an empty value for the top level).
  - `api.experiments(collection?: string | null)`, `api.runLocations(): Promise<{ collection: string | null; name: string }[]>`.
  - `migrateRunScopes(storage: Storage, locations: { collection: string | null; name: string }[]): { moved: string[]; ambiguous: string[]; rename: Record<string, string> }` handles these key families, exactly as the producing code builds them:
    - `fri.rois.exp.<n>` (lib/roi.ts:548)
    - `flir.masks.v1.exp.<n>` (lib/mask.ts:151)
    - `fri.roilabels.v1.exp.<n>` and `fri.roilabels.v1.exp.<n>.mask` (lib/labelDrag.ts:14)
  - `rename` maps `exp.<n>` → `exp.<c>/<n>` for the layout's smartView keys (`exp.<n>:<id>`, lib/smartView.ts:14). They are re-keyed through the layout action `{ type: "renameSmartViewScopes", rename }`.
  - Backend `GET /api/collections/runs` → `[{collection, name}]` across local, the connected drive and the offline index.

- [ ] **Step 1: Write failing tests.**

```ts
test("runKey round-trips and top level stays bare", () => {
  assert.equal(runKey("mattmccoy", "20261102_165506_Run"), "mattmccoy/20261102_165506_Run");
  assert.equal(runKey(null, "20261102_165506_Run"), "20261102_165506_Run");
  assert.deepEqual(parseRunKey("mattmccoy/20261102_165506_Run"), { collection: "mattmccoy", name: "20261102_165506_Run" });
});
test("runPath adds the collection after any query", () => {
  assert.equal(runPath("mattmccoy/r", "/frames?start=0&count=5"), "/api/experiments/r/frames?start=0&count=5&collection=mattmccoy");
  assert.equal(runPath("r"), "/api/experiments/r?collection=");
  assert.equal(runPath("rf-sintering/a b", "/reveal"), "/api/experiments/a%20b/reveal?collection=rf-sintering");
});
```

  - `scopeMigration.test.ts`. The fixture keys are built with the real producers (`offsetsKey`, the roi/mask key formats). Browser storage on `:8000` must not be opened, so the keys cannot be captured.
    - `migrates every key family`: the 4 families for `20261102_165506_Run` at `{collection:"mattmccoy"}` → each value is under the `exp.mattmccoy/20261102_165506_Run` key, and the old key is removed.
    - `never overwrites an existing new key`: if the new key already exists, the old key is kept and is not copied.
    - `leaves ambiguous names`: the same name in `mattmccoy` and `rf-sintering` → `ambiguous` contains it, and nothing moves.
    - `top-level runs keep their key`.
    - `is idempotent`: a second call returns `moved: []`.
  - Layout reducer test (in `lib/layout.test.ts`): `renameSmartViewScopes` turns `{"exp.r:3": {...}}` into `{"exp.mattmccoy/r:3": {...}}` and leaves `live:1` alone.
  - Backend: `test_run_locations_cover_all_libraries`.
- [ ] **Step 2: Run** `cd frontend && node --experimental-strip-types --test 'src/lib/runKey.test.ts' 'src/lib/scopeMigration.test.ts' 'src/lib/layout.test.ts'` and the backend test. Expected: FAIL (modules or action missing; 404).
- [ ] **Step 3: Implement** the libs, the reducer action, and the endpoint. Then convert `api.ts` and the call sites. On mount, App calls `api.runLocations()` → `migrateRunScopes(localStorage, …)` → dispatches `renameSmartViewScopes` if `rename` is non-empty. It logs `console.warn` listing the `ambiguous` names, if any.
- [ ] **Step 4: Run** the frontend gate (all tests and `npx tsc --noEmit`) and the backend gate: green. `grep -n 'encodeURIComponent(name)' src/lib/api.ts` shows only the 2 preset routes.
- [ ] **Step 5: Commit** `feat(ui): address runs by collection; re-key per-run browser state`.

### Task 10: Collection picker, top-bar indicator, "Recording to"

**Files:**
- Create: `frontend/src/lib/collections.ts`, `frontend/src/lib/collections.test.ts`, `frontend/src/components/CollectionPicker.tsx`
- Modify: `frontend/src/lib/api.ts` (`collections`, `addCollection`, `selectCollection`, `CollectionsDoc` type mirroring Task 2/7)
- Modify: `frontend/src/components/ExperimentsPage.tsx` (picker in `.exp-head`, list scoped to `doc.selected`)
- Modify: `frontend/src/App.tsx` (topbar indicator)
- Modify: `frontend/src/components/RecordPanel.tsx`, `frontend/src/components/ArmPanel.tsx`
- Modify: `frontend/src/styles.css` (tokens only)

**Interfaces:**
- Consumes: `CollectionsDoc` and the routes from Tasks 2/5/7.
- Produces:
  - `collectionNameError(s: string): string | null`. It uses the same rules as the backend and is tested on the same lists as `test_valid_collection_names` / `test_rejected_collection_names`.
  - `pickerEntries(doc: CollectionsDoc): { value: string; label: string; disabled: boolean; note: string | null }[]`, with entries in this order:
    - collections alphabetically, with notes `"offline"`, `"on drive only"` or `"on this Mac only"` (both sides → `null`);
    - then `Unsorted (n)`, value `""`, when the local plus drive count is greater than 0 or Unsorted is selected;
    - then unexpected folders, disabled, note `"not a collection or run; left untouched"`.
  - `canRecord(doc: CollectionsDoc): { ok: boolean; reason: string | null }`. The reasons are exactly `"pick a collection before recording"`, plus the offline-only message from Task 7.
  - The picker is disabled while recording or armed, with a title giving the Task 5 lock message.

- [ ] **Step 1: Write failing tests** in `collections.test.ts`:
  - `name rules match the backend lists`;
  - `entries order and notes` (doc with `mattmccoy` on both sides, `rf-sintering` offline, unsorted `{local:1, drive:0}`, unexpected `Old Stuff`);
  - `Unsorted hidden when empty and not selected`;
  - `canRecord blocks null, Unsorted and offline-only`.
- [ ] **Step 2: Run** `node --experimental-strip-types --test src/lib/collections.test.ts`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the lib and wire up the UI:
  - picker plus an "Add user or project" inline form, showing `collectionNameError` live;
  - top-bar `<span className="collection-indicator">` showing the selected name, or "no collection";
  - "Recording to: <name>" in RecordPanel and ArmPanel, with Record/Arm disabled and the reason when `!canRecord`.
- [ ] **Step 4: Run** the frontend gate: green.
- [ ] **Step 5: Not unit-testable (DOM/visual). Run the browser check on a demo operator.**
  - Build: `cd frontend && npx vite build`.
  - Start: `FRI_EXPERIMENTS_ROOT=<scratchpad>/demo-root backend/.venv/bin/python -m flir_research_interface.api.server --port 8765 --backend simulated`.
  - Open `http://127.0.0.1:8765`.
  - Verify:
    - add `demo`, select it → the top bar shows `demo`;
    - Record shows "Recording to: demo";
    - record 2 s → the card appears under `demo` only;
    - while recording, the picker is disabled;
    - selecting Unsorted disables Record with the prompt.
  - Take a screenshot of each state. Stop the demo operator.
- [ ] **Step 6: Commit** `feat(ui): collection picker, top-bar indicator and "Recording to"`.

### Task 11: Unsorted moves, migration panel, global storage label

**Files:**
- Create: `frontend/src/lib/migrationView.ts`, `frontend/src/lib/migrationView.test.ts`, `frontend/src/components/CollectionsMigrationPanel.tsx`
- Modify: `frontend/src/lib/api.ts` (`moveToCollection`, `migrationPlan`, `applyMigration` + types mirroring Task 8)
- Modify: `frontend/src/components/ExperimentsPage.tsx`, `ExperimentCard.tsx` (a "move to collection…" action on cards and in the selection bar)
- Modify: `frontend/src/components/SetupPage.tsx`, `StoragePanel.tsx` (mount the panel; label the totals "all collections, both volumes")
- Modify: `frontend/src/styles.css` (tokens only)

**Interfaces:**
- Consumes: the Task 6 `POST …/collection`; the Task 8 migration routes; the Task 9 `keyOf`.
- Produces:
  - `migrationSummary(plan: MigrationPlanDoc): string`, for example `"92 runs → mattmccoy/ · 90 macOS ._ files removed · 0 conflicts"`, with conflicts and unexpected listed separately.
  - `confirmText(plan): string` lists every `src → dst`. It is shown in the confirm dialog, and the POST carries exactly `plan.moves.map(m => m.name)`.
  - `moveTargets(doc: CollectionsDoc, current: string | null): string[]` lists valid collections other than the current one, and excludes offline-only ones.

- [ ] **Step 1: Write failing tests** in `migrationView.test.ts`:
  - `summary counts` (plan with 92 moves, appledouble 90, 1 conflict);
  - `confirm text lists every move`;
  - `confirm payload is exactly the planned names`;
  - `move targets exclude current and offline-only`.
- [ ] **Step 2: Run** `node --experimental-strip-types --test src/lib/migrationView.test.ts`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the panel:
  - per volume ("This Mac", "<drive label>"): Preview → summary and the full list → "Move N runs into mattmccoy" → `window.confirm(confirmText)` → POST;
  - show moved/failed counts and the log path;
  - the drive section is disabled while the drive is unplugged;
  - a busy 409 is shown verbatim.
  - Then the move-to-collection action, and the Setup storage label.
- [ ] **Step 4: Run** the frontend gate: green.
- [ ] **Step 5: Browser check (not unit-testable), demo operator on `:8765`** with a scratch root holding 3 top-level runs (recorded on the demo) and a scratch "drive" folder registered through Setup.
  - Preview the local migration → 3 moves are listed. Confirm → the runs are under `mattmccoy`, and the log file exists in the scratch root.
  - Record into `demo`, then move one run to Unsorted and back with "move to collection…".
  - Offload to the scratch drive → it lands in `FLIR-recordings/demo/`.
  - Take screenshots.
- [ ] **Step 6: Commit** `feat(ui): migration panel, move runs between collections, global storage label`.

### Task 12: Real-data dry-run acceptance and v0.4.63

**Files:**
- Modify: `backend/flir_research_interface/__init__.py`, `backend/pyproject.toml`, `backend/uv.lock` (the `flir-research-interface` package entry only): `0.4.62` → `0.4.63`.

**Interfaces:**
- Consumes: `plan_migration` (Task 8).

- [ ] **Step 1: Run the real-data dry-run (read-only; the only SSD access in this plan).**
  - Run: `backend/.venv/bin/python -c "from pathlib import Path; from flir_research_interface.collections_migration import plan_migration as p; [print(b, len(x.moves), x.appledouble, x.conflicts, x.unexpected, x.already_in_target) for b in ('/Users/mattmccoy/GaTech Dropbox/Matthew McCoy/FLIR/backend/experiments', '/Volumes/FLIR SSD/FLIR-recordings') for x in [p(Path(b), 'mattmccoy')]]"`, then print every `src → dst`.
  - Expected:
    - local: 1 move (`20261102_165506_Run`), 0 conflicts, 0 unexpected;
    - SSD: 92 moves, 90 AppleDouble, 0 conflicts, 0 unexpected.
  - No path outside `FLIR-recordings` (no `HEATR-data`, `CT_SCANS` or `vpi-runs`) may appear.
  - Before and after, compare `ls -la` of both roots and of `/Volumes/FLIR SSD`: identical.
  - If the SSD is unplugged, record that and run the local half only. Do **not** apply.
- [ ] **Step 2: Real-data listing check, read-only.** Run `scan_root` on the SSD root and print the counts (the same 92 / 0 / 0). Run `offline_runs(local_base, collection=None)` on the real v1 index: 92 entries, none dropped.
- [ ] **Step 3: Bump the version** in the three files, and confirm with `grep -n '0.4.63'`. Do not run `uv lock` or `uv sync` for this; edit the lock entry by name.
- [ ] **Step 4: Run the full backend and frontend gates:** green.
- [ ] **Step 5: Commit** `chore(release): v0.4.63 collections`.
- [ ] **Step 6: Hand off to Matt.**
  - Report the dry-run output verbatim.
  - Deploying to the operator clone (merge, never reset), restarting it, and running the two migration passes from the Setup panel all need his go.
  - Before any restart, check `/api/operator/busy` reports `busy: false`.
