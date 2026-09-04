# External-drive storage (offload) — design

**Goal:** Free up the acquisition machine's disk by moving finished runs to one external drive,
browse/play runs wherever they live, on macOS, Windows and Linux. Recording stays on local disk.

**Decisions (from design chat, 2026-09-03):** offload-only (never record onto the drive); one
external drive at a time; manual moves only; playing a run directly off the drive is supported
(same reader code) and the user judges whether the drive is fast enough.

---

## Model: two libraries, a run lives in exactly one

- **local** — the existing `experiments_root` on the acquisition machine (recording target).
- **drive** — a single registered external volume, using `<mount>/FLIR-recordings/` as its root.

Because offload **moves** (copy → verify → delete source), every run is in exactly one library at
a time. No name collisions, no "which copy is authoritative" — a clean union for the list.

The registered drive path is persisted operator-side in `<experiments_root>/.storage.json`
(git-ignored sidecar), e.g. `{"drive": {"mount": "/Volumes/FieldData", "root": "/Volumes/FieldData/FLIR-recordings"}}`.
It survives restarts. If the drive is not mounted, the library shows **unavailable — reconnect**.

## Volume detection (the cross-platform crux) — grounded in a real probe

`psutil.disk_partitions(all=False)` + `shutil.disk_usage(mount)` enumerate volumes on all three
OSes (psutil is already a dependency). The probe on this Mac showed the trap: it returns ~20
entries — `/`, every `/System/Volumes/*`, and read-only mounted `.dmg`s under `/Volumes`. So we
must **filter to real user drives**, not list them raw:

- **macOS:** keep mounts under `/Volumes/` (exclude `/` and `Macintosh HD`); a real drive is `rw`
  (mounted DMGs are `ro` → excluded). *(captured: `/Volumes/FieldData` rw with real free space is
  selectable; `/Volumes/Spinnaker 4.4.0.246` is `ro` → filtered.)*
- **Linux:** keep mounts under `/media/<user>/`, `/run/media/<user>/`, `/mnt/`; require `rw`.
- **Windows:** keep drive letters whose psutil `opts` include `removable`, plus fixed non-`C:` data
  drives. **Verification gate:** the Windows filter must be checked against a real Windows box
  before that path ships (I could not probe Windows here) — the Mac/Linux filters are grounded.

**Writability is tested, not trusted:** after filtering, confirm a drive is usable by creating
`<mount>/FLIR-recordings/` and writing+deleting a probe file. `ro` in opts is an early reject; a
read-only NTFS drive on macOS is caught by the write probe.

## API (operator)

- `GET  /api/storage/volumes` → `[{label, mount, root, total_bytes, free_bytes, writable, is_registered}]`
  (filtered as above).
- `GET  /api/storage` → `{local: {root, free_bytes, total_bytes}, drive: {…}|null, drive_connected: bool}`.
- `PUT  /api/storage/drive` `{mount}` → validate + write-probe + persist `.storage.json`; 400 if not
  writable/removable.
- `DELETE /api/storage/drive` → forget the registered drive (does not touch its files).
- `POST /api/experiments/{name}/move` `{to: "drive"|"local"}` → start a background move job
  (copy → verify → delete source); returns a job record. Poll `…/move/status`.
- All existing run endpoints resolve a run across both roots and stay confined with `contained()`.

`list_experiments` scans both roots, tagging each run `{library: "local"|"drive", root}`. The
experiments list unions them; disconnected drive → its section shows unavailable.

## The move (data-safety critical) — copy, verify, then delete

Reuse the background-job + progress plumbing already built for derived exports, and the per-run
`KeyedLocks` so a move can't race a render/regenerate of the same run.

1. Refuse if the run is being recorded, if a move/render for it is in flight, or if the target has
   less free space than the run's size.
2. Copy `<name>/` to `<target-root>/<name>.partial/` (per-file, reporting bytes for progress).
3. **Verify** before deleting anything: every file present with matching size, and a SHA-256 match
   on the integrity-critical small files (`metadata.json`, `manifest.json`). (Optional full-checksum
   mode later.)
4. Atomically rename `<name>.partial/` → `<name>/` on the target.
5. **Only now** delete the source `<name>/`.
6. On any failure or drive disconnect mid-move: leave the source intact, delete the partial target,
   surface a clear error. Never a half-state where the run is gone from both.

## UI

- The status-bar `disk …` readout becomes a **Storage** control: `Local · 151 GB free ▾`; the
  dropdown lists detected drives (label, free/total) and lets you register/change/forget the drive.
- A **Setup → Storage** card for the details (registered drive, free space, reconnect help).
- Experiments page: each run card tagged **Local** / **Drive**; a **Move to drive ▸** (or **← local**)
  action with a progress bar; disconnected drive runs shown greyed as **unavailable — reconnect**.
- Playing a run off the drive uses the same reader; a small "on external drive" note sets the
  expectation that speed depends on the drive.

## Out of scope (deferred)

Recording onto the drive; multiple drives / NAS; auto-offload rules; cloud sync.

## Test / verification plan

- Unit (TDD): volume filter (system mounts excluded, ro excluded, real drive kept) against captured
  psutil samples; `.storage.json` round-trip; move verify (size + hash) passes/fails correctly;
  move refuses on low space / recording / in-flight; source survives a simulated mid-copy failure.
- Real-data: on this Mac, register a real USB drive, move a real run, confirm bit-identical copy
  (`metadata.json`/`manifest.json` hashes, chunk sizes), play it off the drive, move it back.
- Cross-platform gate: Mac now; Linux and **Windows** volume filters verified on real machines
  before those installers claim support.
