# External-Drive Offload Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move finished runs to one external drive to free local disk, browse/play runs in either
place, on macOS/Windows/Linux. Recording stays local; moves are manual; every move is copy → verify
→ delete-source so data is never lost.

**Architecture:** A new operator module `storage.py` owns volume detection (psutil, filtered),
the registered-drive config (`.storage.json` sidecar in the local root), and the safe move
(copy→verify→delete). New `/api/storage/*` routes plus a `move` job reuse the existing background-job
+ `KeyedLocks` plumbing in `api/app.py`. `list_experiments` gains a per-run `library` tag and the app
scans both roots and resolves runs across them (confined by `contained()`). Frontend: a Storage
picker in the status bar, a Setup → Storage card, and per-card **Move** actions with progress.

**Tech stack:** Python 3.12, FastAPI, psutil (already a dep), `shutil`, `hashlib`; React/TS; existing
`node --test` and `pytest` suites.

**Grounding:** see `docs/superpowers/specs/2026-09-03-external-drive-storage-design.md`. The macOS
psutil sample and the "filter out ~20 system volumes + read-only DMGs" trap are captured there.

---

## Phase 1 — Volume detection + storage config (backend, pure, no UI)

### Task 1: Drive detection filter

**Files:**
- Create: `backend/flir_research_interface/storage.py`
- Test: `backend/tests/test_storage.py`

- [ ] **Step 1: Write the failing test** (fixtures are *captured* psutil samples, per the data-contract rule — do not invent shapes; copy from the spec's macOS probe)

```python
# test_storage.py
from flir_research_interface.storage import selectable_drives, _Part  # _Part: tiny sdiskpart-like

# captured from psutil.disk_partitions(all=False) on macOS (see spec)
MAC_PARTS = [
    _Part("/dev/disk3s1s1", "/", "apfs", "ro,local,rootfs"),
    _Part("/dev/disk3s5", "/System/Volumes/Data", "apfs", "rw,local"),
    _Part("/dev/disk19s1", "/Volumes/Spinnaker 4.4.0.246", "apfs", "ro,nosuid,local"),  # mounted dmg
    _Part("/dev/diskX", "/Volumes/FieldData", "exfat", "rw,nosuid,local"),  # a real USB drive
]

def test_mac_keeps_only_real_writable_external_volumes():
    usage = {"/Volumes/FieldData": (2_000_000_000_000, 1_500_000_000_000)}  # total, free
    drives = selectable_drives("darwin", MAC_PARTS, usage.__getitem__)
    assert [d["mount"] for d in drives] == ["/Volumes/FieldData"]
    d = drives[0]
    assert d["label"] == "FieldData" and d["free_bytes"] == 1_500_000_000_000

def test_linux_keeps_media_mnt_only():
    parts = [
        _Part("/dev/sda2", "/", "ext4", "rw"),
        _Part("/dev/sdb1", "/media/matt/Field", "exfat", "rw"),
        _Part("/dev/sdc1", "/mnt/ro", "ext4", "ro"),
    ]
    usage = lambda m: (10**12, 10**11)
    mounts = [d["mount"] for d in selectable_drives("linux", parts, usage)]
    assert mounts == ["/media/matt/Field"]
```

- [ ] **Step 2: Run it, watch it fail** — `cd backend && uv run pytest tests/test_storage.py -q` → ImportError / assertion.

- [ ] **Step 3: Implement `selectable_drives`**

```python
# storage.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import shutil, psutil

@dataclass(frozen=True)
class _Part:
    device: str; mountpoint: str; fstype: str; opts: str

def _live_parts() -> list[_Part]:
    return [_Part(p.device, p.mountpoint, p.fstype, p.opts) for p in psutil.disk_partitions(all=False)]

def selectable_drives(
    platform: str,
    parts: list[_Part] | None = None,
    usage: Callable[[str], tuple[int, int]] | None = None,  # mount -> (total, free)
) -> list[dict[str, Any]]:
    parts = _live_parts() if parts is None else parts
    usage = usage or (lambda m: (shutil.disk_usage(m).total, shutil.disk_usage(m).free))
    out: list[dict[str, Any]] = []
    for p in parts:
        if not _is_external(platform, p):
            continue
        try:
            total, free = usage(p.mountpoint)
        except OSError:
            continue
        out.append({
            "label": Path(p.mountpoint).name or p.device,
            "mount": p.mountpoint, "fstype": p.fstype,
            "total_bytes": total, "free_bytes": free,
            "read_only": "ro" in p.opts.split(","),
        })
    return out

def _is_external(platform: str, p: _Part) -> bool:
    opts = p.opts.split(",")
    if "ro" in opts:
        return False  # read-only mounts (system, dmgs, ro NTFS) are not offload targets
    if platform == "darwin":
        return p.mountpoint.startswith("/Volumes/") and Path(p.mountpoint).name != "Macintosh HD"
    if platform == "linux":
        return any(p.mountpoint.startswith(pre) for pre in ("/media/", "/run/media/", "/mnt/")) \
            and p.mountpoint not in ("/mnt",)
    if platform == "win32":
        # NOTE: verify on a real Windows box before shipping. Removable, or a fixed non-system drive.
        drive = p.mountpoint.rstrip("\\/").upper()
        return ("removable" in opts) or (drive != "C:" and p.fstype != "")
    return False
```

- [ ] **Step 4: Run, watch pass.** `uv run pytest tests/test_storage.py -q` → PASS.

- [ ] **Step 5: Commit** — `feat(storage): filtered cross-platform external-drive detection`

### Task 2: Storage config sidecar (registered drive, persisted)

**Files:** Modify `backend/flir_research_interface/storage.py`; Test `backend/tests/test_storage.py`

- [ ] **Step 1: Failing test**

```python
def test_storage_config_round_trip_and_absent_default(tmp_path):
    from flir_research_interface.storage import load_storage_config, save_storage_config
    assert load_storage_config(tmp_path) == {"drive": None}
    save_storage_config(tmp_path, {"drive": {"mount": "/Volumes/F", "root": "/Volumes/F/FLIR-recordings"}})
    assert load_storage_config(tmp_path)["drive"]["mount"] == "/Volumes/F"

def test_register_drive_writes_probe_and_rejects_readonly(tmp_path, monkeypatch):
    from flir_research_interface import storage
    drive = tmp_path / "FieldData"; drive.mkdir()
    cfg = storage.register_drive(tmp_path, str(drive))  # local_root=tmp_path
    assert cfg["drive"]["root"] == str(drive / "FLIR-recordings")
    assert (drive / "FLIR-recordings").is_dir()
    # a path we cannot write to raises ValueError
    import pytest
    with pytest.raises(ValueError):
        storage.register_drive(tmp_path, "/nonexistent/xyz")
```

- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** `load_storage_config`/`save_storage_config` (atomic write to `<local_root>/.storage.json`, mirroring `recording/metadata.py:_atomic_write`) and `register_drive(local_root, mount)` — validate the mount is a directory, create `<mount>/FLIR-recordings/`, write+delete a probe file (raise `ValueError` if not writable), persist, return the config. Add `forget_drive(local_root)`.
- [ ] **Step 4: Run, watch pass.**
- [ ] **Step 5: Commit** — `feat(storage): registered-drive config with write-probe validation`

---

## Phase 2 — Multi-library listing + run resolution (backend)

### Task 3: Tag each run with its library and scan both roots

**Files:** Modify `backend/flir_research_interface/playback/reader.py` (`list_experiments`); Modify `backend/flir_research_interface/api/app.py` (experiments list route, `_exp_dir`); Test `backend/tests/test_storage_api.py` (new)

- [ ] **Step 1: Failing test** — start the app with `experiments_root=local`, register a fake drive dir containing a hand-built run folder, `GET /api/experiments` returns runs from both, each tagged `library`:

```python
def test_experiments_list_unions_local_and_drive(tmp_path):
    local = tmp_path / "local"; drive = tmp_path / "drive" / "FLIR-recordings"
    # record one run into local via the sim (reuse the _record helper pattern), and
    # copy a minimal run dir into `drive` (or move it via the API in a later task).
    ...
    with _client(local) as c:
        c.put("/api/storage/drive", json={"mount": str(tmp_path / "drive")})
        items = c.get("/api/experiments").json()
        libs = {e["name"]: e["library"] for e in items}
        assert set(libs.values()) == {"local", "drive"}
```

- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement.** Add `library` + `root` to each dict from `list_experiments` (pass a `library` label param). In `app.py`, add `def _roots() -> list[tuple[str, Path]]` returning `[("local", experiments_root)]` plus `("drive", drive_root)` when a drive is registered **and mounted**. The experiments list route concatenates `list_experiments(root, library=lib)` over `_roots()`. Change `_exp_dir(name)` to search each root and return the first containing `name` (still `contained()`-guarded); 404 if in none. Add `drive_connected` to `GET /api/storage`.
- [ ] **Step 4: Run, watch pass.**
- [ ] **Step 5: Commit** — `feat(storage): union experiments across local + drive, resolve runs across roots`

---

## Phase 3 — The move (data-safety core)

### Task 4: `verify_copy` (size for all files, sha256 for the critical small ones)

**Files:** Modify `storage.py`; Test `test_storage.py`

- [ ] **Step 1: Failing test**

```python
def test_verify_copy_passes_on_identical_and_fails_on_mismatch(tmp_path):
    from flir_research_interface.storage import verify_copy
    src = tmp_path / "a"; dst = tmp_path / "b"
    for d in (src, dst):
        (d / "sub").mkdir(parents=True)
        (d / "metadata.json").write_text('{"x":1}')
        (d / "sub" / "chunk").write_bytes(b"0123456789")
    assert verify_copy(src, dst) is None  # None == OK
    (dst / "sub" / "chunk").write_bytes(b"012345678")  # size differs
    assert "chunk" in verify_copy(src, dst)  # returns a reason string on failure
    (dst / "sub" / "chunk").write_bytes(b"0123456789")
    (dst / "metadata.json").write_text('{"x":2}')  # same size, different bytes
    assert "metadata.json" in verify_copy(src, dst)  # hashed criticals catch this
```

- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** `verify_copy(src, dst) -> str | None`: walk `src`; every file must exist in `dst` with equal `st_size`; for `CRITICAL = {"metadata.json", "manifest.json"}` also compare `sha256`. Return `None` when all good, else a human reason.
- [ ] **Step 4: Run, watch pass.**
- [ ] **Step 5: Commit** — `feat(storage): verify_copy (sizes + hashed critical files)`

### Task 5: `move_experiment` (copy → verify → atomic rename → delete source)

**Files:** Modify `storage.py`; Test `test_storage.py`

- [ ] **Step 1: Failing test**

```python
def test_move_experiment_copies_verifies_and_deletes_source(tmp_path):
    from flir_research_interface.storage import move_experiment
    src_root = tmp_path / "local"; dst_root = tmp_path / "drive"
    run = src_root / "run1"; (run / "thermal.zarr").mkdir(parents=True)
    (run / "metadata.json").write_text('{"a":1}')
    (run / "thermal.zarr" / "0.0.0").write_bytes(b"x" * 1000)
    seen = []
    move_experiment(run, dst_root, on_progress=lambda done, total: seen.append((done, total)))
    assert not run.exists()                       # source gone only after verify
    assert (dst_root / "run1" / "metadata.json").read_text() == '{"a":1}'
    assert not (dst_root / "run1.partial").exists()  # temp cleaned
    assert seen and seen[-1][0] == seen[-1][1]    # progress reached 100%

def test_move_keeps_source_when_target_has_no_space(tmp_path, monkeypatch):
    ... monkeypatch shutil.disk_usage to report tiny free ...
    with pytest.raises(ValueError): move_experiment(run, dst_root)
    assert run.exists()  # untouched
```

- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** `move_experiment(src_run, dst_root, *, on_progress=None)`:
  1. Compute `src` size; if `shutil.disk_usage(dst_root).free < size * 1.05` → `ValueError("not enough space")`.
  2. Copy to `dst_root/<name>.partial/` per file, calling `on_progress(bytes_done, bytes_total)`.
  3. `reason = verify_copy(src_run, partial)`; if reason → delete partial, `RuntimeError(reason)`.
  4. `os.replace(partial, dst_root/<name>)` (atomic on same fs).
  5. `shutil.rmtree(src_run)` — the *only* deletion, after verify+rename.
  6. On any exception after step 2: `shutil.rmtree(partial, ignore_errors=True)`, leave `src_run` intact, re-raise.
- [ ] **Step 4: Run, watch pass.**
- [ ] **Step 5: Commit** — `feat(storage): move_experiment (copy, verify, then delete source)`

---

## Phase 4 — Storage API + move job (backend wiring)

### Task 6: `/api/storage/*` routes + the move job

**Files:** Modify `backend/flir_research_interface/api/app.py`; Test `backend/tests/test_storage_api.py`

- [ ] **Step 1: Failing test** — `GET /api/storage/volumes` lists a fake drive; `PUT /api/storage/drive {mount}` registers it (`GET /api/storage` then shows it, `drive_connected: true`); `POST /api/experiments/{name}/move {to:"drive"}` returns `{state:"running"}`, poll `…/move/status` to `done`, run now lists under `library:"drive"` and is gone from local; low-space and unknown-run cases return 4xx. (Model the move-job test on `test_api_derived.py`.)
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement.** Add `app.state.move_jobs = {}`. Routes: `GET /api/storage/volumes` (→ `selectable_drives()`, mark `is_registered`), `GET /api/storage`, `PUT /api/storage/drive` (`storage.register_drive`, 400 on `ValueError`), `DELETE /api/storage/drive`. `POST /api/experiments/{name}/move` mirrors `export_derived_route`: resolve the run's current root and the target root, refuse if recording / already moving / low space, then a background job that acquires `app.state.render_locks.get(name)` (so a move can't race a render) and runs `move_experiment` in a threadpool with `on_progress` updating the job. `GET …/move/status` returns the record. Refuse move if the drive is unregistered/disconnected (409).
- [ ] **Step 4: Run, watch pass.**
- [ ] **Step 5: Commit** — `feat(api): storage routes + background move job (lock-guarded)`

---

## Phase 5 — Frontend: Storage picker, Setup card, move UI

### Task 7: storage API client + types

**Files:** Modify `frontend/src/lib/api.ts`; add `library?: "local"|"drive"` to `Experiment`.

- [ ] Add `api.storage()`, `api.storageVolumes()`, `api.registerDrive(mount)`, `api.forgetDrive()`, `api.moveExperiment(name, to)`, `api.moveStatus(name)`; interfaces `Volume`, `StorageInfo`, `MoveJob`. (No test; type-checked. Verify: `npx tsc --noEmit`.)
- [ ] Commit — `feat(api-client): storage + move endpoints`

### Task 8: Storage control in the status bar + Setup → Storage card

**Files:** Modify `frontend/src/components/studio/StatusBar.tsx` (the `disk … GB` readout → a Storage dropdown); Create `frontend/src/components/StoragePanel.tsx`; Modify `frontend/src/components/SetupPage.tsx` (add a "Storage" card).

- [ ] The status-bar readout becomes `Local · {free} GB ▾`; the dropdown lists `api.storageVolumes()` with free/total and a Register/Change/Forget action calling `api.registerDrive`/`forgetDrive`. The Setup card shows the registered drive, its free space, connected/disconnected, and reconnect help. Verify in the browser (per `<verification_workflow>`): register a real drive, see free space; forget it.
- [ ] Commit — `feat(ui): storage picker in the status bar + Setup storage card`

### Task 9: Library tag + Move action on experiment cards

**Files:** Modify `frontend/src/components/ExperimentCard.tsx`, `frontend/src/components/ExperimentsPage.tsx`.

- [ ] Each card shows a **Local**/**Drive** tag. Add a **Move to drive ▸** (or **← local**) button that calls `api.moveExperiment` then polls `api.moveStatus`, showing a `ProgressBar` (reuse the pattern/CSS from `ExportSection`), and calls the page's `load()` on done. Disable when no drive is registered (tooltip: register one in the status bar). A run whose library is the (currently disconnected) drive renders greyed with **unavailable — reconnect** and no actions. Verify in the browser.
- [ ] Commit — `feat(ui): per-run library tag + move-to-drive with progress`

---

## Phase 6 — Real-data + cross-platform verification (gates, not code)

### Task 10: Real-drive end-to-end on macOS

- [ ] With a real USB drive on the dev Mac: register it; move a real run; confirm `metadata.json` + `manifest.json` sha256 match the originals and every chunk size matches; the run now lists under Drive and is gone locally; play it off the drive; move it back to local. Record the observed read speed off the drive in the PR. **Do not delete-source unless verify passed** — confirm that path by watching a run survive a deliberately-interrupted move (unplug mid-copy, or kill the job) with the source intact.

### Task 11: Linux + Windows detection gate

- [ ] Confirm `selectable_drives("linux", …)` against a real Linux mount (`/media/<user>/…`).
- [ ] Confirm the Windows filter on a real Windows box; adjust `_is_external("win32", …)` if removable/fixed reporting differs. The Windows installer must not claim drive support until this passes (spec verification plan).

---

## Self-review notes
- Every external data shape (psutil parts, disk_usage) is either captured from the real probe (spec)
  or read live — no invented fixtures (data-contract rule).
- The only deletion in the whole feature is `move_experiment` step 5, after verify + atomic rename.
- Move reuses the existing `KeyedLocks` so it can't race a render/regenerate of the same run.
- `_exp_dir` resolution and every new path stay behind `contained()`.
