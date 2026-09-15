# Experiment organization: stars, tags, multi-select bulk actions

**Date:** 2026-09-15
**Status:** approved design, ready for an implementation plan

## Goal

Let the user organize a growing list of experiments without cluttering the experiments page:
**star** important runs, attach **free-form tags** (with autocomplete), **filter/sort** by star and
tag, and act on **many runs at once** (move to/from the drive, tag, star, delete) via a deliberate
multi-select mode.

## Principles / non-goals

- **Clutter is the enemy.** The resting card grid stays almost exactly as it is today. Selection UI
  and bulk actions only appear when the user opts in. Tags render only when a run actually has them.
- **Organization metadata travels with the data.** It lives in each run's own folder, so it follows
  the run across the Mac/Windows/Linux machines and the external SSD (consistent with the offload
  work). No central index.
- **Not building:** tag colors, tag hierarchies/renaming UI, a dedicated tag-management screen, a
  separate "labels" tab, or always-on checkboxes. Tags are just strings kept consistent by
  autocomplete.

---

## 1. Data model & storage (backend)

### Sidecar file

Each run folder gets **`labels.json`** alongside `metadata.json`:

```json
{ "starred": true, "tags": ["doped", "8020mix", "paper-fig3"] }
```

- Absent file ⇒ `{"starred": false, "tags": []}` (the default; most runs have no sidecar).
- It is ordinary run data: the move copies it intact (it is **not** OS junk and **not** in
  `CRITICAL_FILES`, so it is copied and size-verified but not checksummed), so stars/tags travel to
  the drive and to other machines automatically.
- It is small and rewritten atomically (write temp + `os.replace`) so a crash never corrupts it.

### New module `flir_research_interface/labels.py`

Pure, dependency-free, unit-tested:

- `normalize_tags(raw: Iterable[str]) -> list[str]` — trim each tag, drop empties, collapse internal
  whitespace to single spaces, cap length at 40 chars, de-duplicate **case-insensitively** while
  **preserving the first-seen display casing**, and keep input order. This is the single source of
  truth for what a valid tag set is.
- `read_labels(run_dir: Path) -> dict` — returns `{"starred": bool, "tags": list[str]}`; tolerant of
  a missing/blank/corrupt file (returns the default, never raises).
- `write_labels(run_dir: Path, *, starred: bool, tags: Iterable[str]) -> dict` — normalizes tags,
  writes `labels.json` atomically, returns the stored dict.

### API

- `GET /api/experiments` — each item gains `"starred": bool` and `"tags": list[str]`, read via
  `labels.read_labels(root / name)` in `app.py`'s `experiments()` enrichment (same place `size_bytes`
  is added today). No change to `list_experiments` in `reader.py`.
- `PUT /api/experiments/{name}/labels` — body `{ "starred": bool, "tags": [str, ...],
  "library": "local"|"drive"|null }`; writes the sidecar via `write_labels` and returns the stored
  `{starred, tags}`. When `library` is given it targets that copy's folder (a run can exist on both
  local **and** drive with independent sidecars); when null it resolves local-first via the existing
  `_exp_dir(name)`. 404 if the run (in that library) is unknown. Cross-origin writes already require
  the `X-FRI-Client: 1` header via the existing guard — no change needed. The frontend always sends
  the card's own `library` so the correct copy is edited.
- Bulk star/tag are **N independent `PUT` calls from the frontend** (cheap metadata writes); there is
  no bulk labels endpoint. Bulk move reuses the existing per-run `/move`; bulk delete reuses the
  existing per-run `DELETE`.

### Tag universe (for autocomplete)

Computed **on the frontend** from the already-loaded experiments list (union of every item's `tags`,
frequency-sorted). No extra endpoint. It refreshes with the normal 5 s experiments poll.

---

## 2. Frontend

### Types & API client (`src/lib/api.ts`)

- `Experiment` gains `starred?: boolean` and `tags?: string[]`.
- `api.setLabels(name, { starred, tags, library }) => PUT /api/experiments/{name}/labels`
  (the card passes its own `library` so the correct copy is edited).

### Pure logic (extracted + unit-tested, `src/lib/organize.ts`)

- `normalizeTag(s)` / `mergeTags(existing, add)` — mirror the backend normalization so the UI never
  sends junk (trim, dedupe case-insensitively, cap length).
- `suggestTags(all: string[], query: string, exclude: string[]) -> string[]` — autocomplete: tags
  containing `query` (case-insensitive), most-used first, excluding ones already applied, capped ~8.
- `tagUniverse(items) -> {tag: string, count: number}[]` — frequency-sorted union.
- `filterExperiments(items, { query, starredOnly, tags })` — `query` matches name **or** any tag;
  `starredOnly` keeps starred; `tags` keeps runs having **all** selected tags (AND).
- `sortExperiments(items, sort)` — existing `newest|name|duration` plus `starred` (starred first,
  then newest within each group).
- `selectionReducer` — a small reducer for the Set of selected names: `toggle`, `range` (shift-click
  from an anchor over the currently-shown order), `selectAll(shown)`, `clear`.

### Card (`src/components/ExperimentCard.tsx`) — resting state barely changes

- **Star**: a small hollow/solid star button in a card corner; click toggles via `api.setLabels`
  (optimistic, reverts on error), independent of selection mode.
- **Tags**: render as small chips **only when `tags.length > 0`**. Each chip click filters the page
  by that tag. A subtle **`＋`** affordance opens the tag popover.
- **Tag popover** (`src/components/TagPopover.tsx`): a text input with an autocomplete dropdown
  (`suggestTags`), the current tags as removable (`×`) chips, Enter/click adds, Esc closes. Writes
  the whole tag set via `api.setLabels`. Reused for a single card and (headless) for the bulk bar.
- **Selection**: when the page is in selection mode, the card shows a checkbox; clicking anywhere on
  the card toggles selection instead of opening; shift-click range-selects.

### Experiments page (`src/components/ExperimentsPage.tsx`)

- **Header additions (compact):** a `★ starred` toggle; a `tags ▾` multiselect of the tag universe;
  a **Select** toggle that enters selection mode. Active filters (star + each tag) show as removable
  chips so the current filter is always obvious. Search now also matches tags (via `filterExperiments`).
  Sort dropdown gains `starred first`. Filter/sort/selection state persists in `localStorage`.
- **Selection mode + floating action bar** (`src/components/SelectionBar.tsx`): appears only while
  selecting. Shows `N selected`, `select all (shown)`, `clear`, and actions:
  - **Move to drive / ← local** — queues the selected runs through the existing move machinery
    sequentially; the bar shows aggregate progress (`moving 3/7…`) and per-run errors are surfaced
    without aborting the rest.
  - **Tag…** — opens the shared tag popover; the chosen tags are **added** (union) to every selected
    run via N `setLabels` calls.
  - **★ Star / ☆ Unstar** — sets `starred` on every selected run.
  - **Delete** — one confirmation dialog listing the count and names; then N deletes. (Single-card
    delete keeps its existing typed-confirm; the bulk dialog is a single Yes/No for the batch.)
  - On completion the list refetches and selection clears.

### Styling

New elements (`.star`, `.tag-chip`, `.tag-popover`, `.selection-bar`, checkboxes) use existing design
tokens only (`--accent`, `--accent-ink`, `--muted`, `--line`, `--panel`, `--scrim`, `--err`) so the
theme test (no color literals in `styles.css`) stays green, and honor light/dark automatically.

---

## 3. Error handling & edge cases

- Corrupt/blank `labels.json` ⇒ treated as default, never crashes a listing (tolerant `read_labels`).
- A run present on **both** local and drive has independent sidecars; labels are shown/edited per
  card (each card already keyed by `library:name`).
- Optimistic star/tag writes revert and surface a note on failure.
- Bulk actions are best-effort: one failure (e.g. a run mid-record refuses to move) reports that run
  and continues the rest; the summary says how many succeeded.
- Tag normalization is enforced on **both** ends; the backend is authoritative.
- Empty tag list and `starred:false` are valid; writing them is allowed (and may leave a tiny
  sidecar — acceptable, or we may delete the sidecar when it equals the default to avoid clutter;
  decide in the plan, default to "leave it").

---

## 4. Testing

**Backend (pytest, TDD):**
- `labels.normalize_tags`: trim, drop empty, collapse whitespace, length cap, case-insensitive dedupe
  preserving first casing, order preserved.
- `read_labels`/`write_labels`: round-trip; missing file ⇒ default; corrupt file ⇒ default; atomic
  rewrite; normalization applied on write.
- API: `GET /api/experiments` includes `starred`/`tags`; `PUT …/labels` writes and returns; unknown
  run ⇒ 404; a run **moved to the drive carries its `labels.json`** (extend a storage/move test).

**Frontend (`node --test`):**
- `organize.ts`: `normalizeTag`, `suggestTags` (ranking + exclusion + query match), `tagUniverse`,
  `filterExperiments` (name-or-tag match, starred-only, AND over tags), `sortExperiments` (starred
  first), `selectionReducer` (toggle/range/selectAll/clear).
- Theme test stays green (no color literals).

**Browser verification:** star toggle persists; add/remove tags via popover with autocomplete; filter
by a tag chip and the `★` toggle; enter selection mode, multi-select, and run each bulk action;
confirm labels survive a move to the drive and back.

---

## 5. File map

- Create: `backend/flir_research_interface/labels.py`, `backend/tests/test_labels.py`,
  `frontend/src/lib/organize.ts`, `frontend/src/lib/organize.test.ts`,
  `frontend/src/components/TagPopover.tsx`, `frontend/src/components/SelectionBar.tsx`.
- Modify: `backend/flir_research_interface/api/app.py` (enrich `experiments()`, add `PUT …/labels`),
  `backend/tests/test_storage.py` (labels travel on move), `frontend/src/lib/api.ts`,
  `frontend/src/components/ExperimentCard.tsx`, `frontend/src/components/ExperimentsPage.tsx`,
  `frontend/src/styles.css`. Version bump as usual.
