# Experiment Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Star runs, attach free-form tags (with autocomplete), filter/sort by star and tag, and act on many runs at once (move, tag, star, delete) — without cluttering the experiments page.

**Architecture:** A per-run `labels.json` sidecar (travels with the data) read/written by a new pure `labels` module and a `PUT /api/experiments/{name}/labels` endpoint; `GET /api/experiments` enriched with `starred`/`tags`. Frontend: pure logic in `organize.ts` (TDD), a `TagPopover`, star + chips on the card, and an opt-in selection mode with a floating `SelectionBar`.

**Tech Stack:** FastAPI + pytest (backend), React + TypeScript + `node --test` (frontend). Version single-sourced in `backend/flir_research_interface/__init__.py`.

**Careful-mode notes (the user asked us to be careful):** the experiments page is in daily use. Do backend first (additive, no behavior change), then pure frontend logic, then wire UI last. Run the full suite after each task. Every color goes through a token (theme test). Bulk actions are best-effort and never abort the batch on one failure.

Spec: `docs/superpowers/specs/2026-09-15-experiment-organization-design.md`.

---

### Task 1: Backend `labels` module (pure, sidecar I/O)

**Files:**
- Create: `backend/flir_research_interface/labels.py`
- Test: `backend/tests/test_labels.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_labels.py
"""Per-run organization sidecar: normalize tags, read/write labels.json (tolerant + atomic)."""
from __future__ import annotations

from pathlib import Path

from flir_research_interface.labels import normalize_tags, read_labels, write_labels


def test_normalize_tags_trims_dedupes_caseins_preserves_first_casing_and_order() -> None:
    out = normalize_tags(["  Doped ", "doped", "8020mix", "", "   ", "a" * 60, "  two words  "])
    assert out == ["Doped", "8020mix", "a" * 40, "two words"]  # trimmed, deduped, capped, ordered


def test_read_labels_defaults_when_missing_or_corrupt(tmp_path: Path) -> None:
    assert read_labels(tmp_path) == {"starred": False, "tags": []}
    (tmp_path / "labels.json").write_text("{not json")
    assert read_labels(tmp_path) == {"starred": False, "tags": []}


def test_write_labels_normalizes_and_round_trips_atomically(tmp_path: Path) -> None:
    stored = write_labels(tmp_path, starred=True, tags=["Doped", "doped", " x "])
    assert stored == {"starred": True, "tags": ["Doped", "x"]}
    assert read_labels(tmp_path) == {"starred": True, "tags": ["Doped", "x"]}
    assert not list(tmp_path.glob("*.tmp*"))  # temp file cleaned up (atomic replace)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --directory backend python -m pytest tests/test_labels.py -q`
Expected: FAIL (ImportError: no module named labels).

- [ ] **Step 3: Implement `labels.py`**

```python
# backend/flir_research_interface/labels.py
"""Per-run organization metadata (star + free-form tags) stored in a ``labels.json`` sidecar.

The sidecar lives inside the run folder so stars/tags travel with the data across machines and the
external drive. All access is tolerant (a missing or corrupt file reads as the default) and writes
are atomic (temp + ``os.replace``) so a crash never corrupts it.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

LABELS_FILE = "labels.json"
_MAX_TAG_LEN = 40


def normalize_tags(raw: Iterable[str]) -> list[str]:
    """Trim, collapse internal whitespace, drop empties, cap length, de-duplicate case-insensitively
    (keeping the first-seen casing), preserving order. Single source of truth for a valid tag set."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = " ".join(str(item).split())[:_MAX_TAG_LEN].strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def read_labels(run_dir: Path | str) -> dict[str, Any]:
    """``{"starred": bool, "tags": [str]}``; the default on a missing/blank/corrupt file."""
    default = {"starred": False, "tags": []}
    path = Path(run_dir) / LABELS_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    return {"starred": bool(data.get("starred", False)),
            "tags": normalize_tags(data.get("tags") or [])}


def write_labels(run_dir: Path | str, *, starred: bool, tags: Iterable[str]) -> dict[str, Any]:
    """Normalize and atomically write the sidecar; return the stored dict."""
    run_dir = Path(run_dir)
    stored = {"starred": bool(starred), "tags": normalize_tags(tags)}
    run_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".labels-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(stored, f)
        os.replace(tmp, run_dir / LABELS_FILE)
    finally:
        Path(tmp).unlink(missing_ok=True)  # no-op after a successful replace
    return stored


__all__ = ["LABELS_FILE", "normalize_tags", "read_labels", "write_labels"]
```

- [ ] **Step 4: Run the tests — expect PASS**, then `uv run ruff check flir_research_interface/labels.py tests/test_labels.py`.

- [ ] **Step 5: Commit** `feat(labels): per-run star + tags sidecar (labels.json)`.

---

### Task 2: API — enrich `GET /experiments`, add `PUT …/labels`

**Files:**
- Modify: `backend/flir_research_interface/api/app.py`
- Test: `backend/tests/test_api_labels.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_labels.py
"""Labels API: GET /experiments carries starred/tags; PUT writes the sidecar (per library)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app


def _client(tmp: Path) -> TestClient:
    app = create_app(default_backend="simulated", experiments_root=tmp)
    return TestClient(app)


def _make_run(root: Path, name: str = "run1") -> None:
    # a minimal readable experiment is not required for the labels endpoints; a folder is enough,
    # but list_experiments needs a real store — reuse the recorder helper if present. Here we only
    # test the labels endpoints against a run dir that exists.
    (root / name).mkdir(parents=True)


def test_put_labels_writes_sidecar_and_get_returns_it(tmp_path: Path) -> None:
    _make_run(tmp_path)
    c = _client(tmp_path)
    r = c.put("/api/experiments/run1/labels",
              json={"starred": True, "tags": ["Doped", "doped", " x "]},
              headers={"X-FRI-Client": "1"})
    assert r.status_code == 200
    assert r.json() == {"starred": True, "tags": ["Doped", "x"]}
    from flir_research_interface.labels import read_labels
    assert read_labels(tmp_path / "run1") == {"starred": True, "tags": ["Doped", "x"]}


def test_put_labels_unknown_run_is_404(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.put("/api/experiments/nope/labels", json={"starred": False, "tags": []},
              headers={"X-FRI-Client": "1"})
    assert r.status_code == 404
```

Note: if `create_app`'s signature differs, mirror `test_storage_api.py`/`test_api.py`'s construction. Confirm the label endpoint enriches `GET /experiments` with a run that `list_experiments` can read — extend with a recorder-made run if the simple folder is filtered out.

- [ ] **Step 2: Run — expect FAIL** (no `/labels` route).

Run: `uv run --directory backend python -m pytest tests/test_api_labels.py -q`

- [ ] **Step 3: Implement in `app.py`**

Add import near the other imports:
```python
from flir_research_interface import labels as labels_mod
```

Add a request model near `MoveRequest`:
```python
class LabelsRequest(BaseModel):
    starred: bool = False
    tags: list[str] = []
    library: str | None = None  # "local"|"drive"|None (None = first found, local-first)
```

Enrich `experiments()` (add one line inside the loop, after `size_bytes`):
```python
        for lib, root in _roots():
            for it in list_experiments(root, library=lib):
                it["size_bytes"] = _dir_size(root / str(it.get("name", "")))
                it.update(labels_mod.read_labels(root / str(it.get("name", ""))))
                items.append(it)
```

Add a helper to resolve a run dir in a specific library, then the route (place beside `move_status`):
```python
    def _exp_dir_in(name: str, library: str | None) -> Path:
        if library is None:
            return _exp_dir(name)  # local-first, 404 if unknown
        for lib, root in _roots():
            if lib == library:
                d = root / name
                if d.is_dir() and contained(root, d):
                    return d
                raise HTTPException(404, f"experiment {name!r} not found in {library}")
        raise HTTPException(404, f"library {library!r} is not available")

    @app.put("/api/experiments/{name}/labels")
    def set_labels(name: str, req: LabelsRequest) -> dict[str, Any]:
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise HTTPException(400, "invalid experiment name")
        run = _exp_dir_in(name, req.library)
        return labels_mod.write_labels(run, starred=req.starred, tags=req.tags)
```

- [ ] **Step 4: Run the labels tests + the full api suite — expect PASS**; ruff clean.

- [ ] **Step 5: Commit** `feat(api): starred/tags on /experiments + PUT /experiments/{name}/labels`.

---

### Task 3: Labels travel with a move

**Files:**
- Test: `backend/tests/test_storage.py` (add one test)

- [ ] **Step 1: Add the failing/curiosity test** (it should already pass, since `move_experiment` copies every non-junk file — this locks the behavior in):

```python
def test_move_carries_the_labels_sidecar(tmp_path: Path) -> None:
    from flir_research_interface import storage
    from flir_research_interface.labels import read_labels, write_labels

    src_root = tmp_path / "local"; dst_root = tmp_path / "drive"; dst_root.mkdir(parents=True)
    run = _make_run(src_root)
    write_labels(run, starred=True, tags=["doped"])
    dest = storage.move_experiment(run, dst_root)
    assert read_labels(dest) == {"starred": True, "tags": ["doped"]}
```

- [ ] **Step 2: Run it.** If it passes first try, good (documents the guarantee). If it fails (e.g. the sidecar name is skipped), fix `storage._is_os_junk` to not skip `labels.json` and re-run.

- [ ] **Step 3: Commit** `test(storage): labels.json travels with a moved run`.

---

### Task 4: Frontend types + API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1** (no unit test; type + client wiring, verified by tsc + later tests): add to the `Experiment` interface:
```ts
  starred?: boolean;
  tags?: string[];
```
and add the client method near `moveExperiment`:
```ts
  setLabels: (name: string, body: { starred: boolean; tags: string[]; library?: "local" | "drive" }) =>
    j<{ starred: boolean; tags: string[] }>(req(`/api/experiments/${encodeURIComponent(name)}/labels`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })),
```

- [ ] **Step 2:** `npx tsc --noEmit` clean. Commit `feat(api-client): setLabels + starred/tags on Experiment`.

---

### Task 5: Frontend pure logic `organize.ts` (TDD)

**Files:**
- Create: `frontend/src/lib/organize.ts`, `frontend/src/lib/organize.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/lib/organize.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeTag, suggestTags, tagUniverse, filterExperiments, sortExperiments,
  selectionReducer, type SelectionState,
} from "./organize.ts";

type E = { name: string; starred?: boolean; tags?: string[]; started_utc?: string | null };
const items: E[] = [
  { name: "b", starred: true, tags: ["Doped", "8020mix"], started_utc: "2026-09-02T00:00:00Z" },
  { name: "a", starred: false, tags: ["control"], started_utc: "2026-09-01T00:00:00Z" },
  { name: "c", starred: false, tags: [], started_utc: "2026-09-03T00:00:00Z" },
];

test("normalizeTag trims and caps", () => {
  assert.equal(normalizeTag("  Doped  "), "Doped");
  assert.equal(normalizeTag("two   words"), "two words");
  assert.equal(normalizeTag(""), "");
});

test("tagUniverse counts and frequency-sorts", () => {
  const u = tagUniverse([{ tags: ["x", "y"] }, { tags: ["x"] }] as E[]);
  assert.deepEqual(u.map((t) => t.tag), ["x", "y"]);
  assert.equal(u[0].count, 2);
});

test("suggestTags: case-insensitive contains, excludes applied, ranked", () => {
  const s = suggestTags(["Doped", "control", "doped-batch2"], "dop", ["Doped"]);
  assert.deepEqual(s, ["doped-batch2"]); // matches, not the already-applied "Doped"
});

test("filterExperiments matches name or tag, starred-only, AND over tags", () => {
  assert.deepEqual(filterExperiments(items, { query: "doped", starredOnly: false, tags: [] }).map((e) => e.name), ["b"]);
  assert.deepEqual(filterExperiments(items, { query: "", starredOnly: true, tags: [] }).map((e) => e.name), ["b"]);
  assert.deepEqual(filterExperiments(items, { query: "", starredOnly: false, tags: ["Doped", "8020mix"] }).map((e) => e.name), ["b"]);
});

test("sortExperiments: starred first then newest", () => {
  assert.deepEqual(sortExperiments(items, "starred").map((e) => e.name), ["b", "c", "a"]);
});

test("selectionReducer toggle/range/selectAll/clear", () => {
  let s: SelectionState = { anchor: null, selected: new Set<string>() };
  s = selectionReducer(s, { type: "toggle", name: "a" });
  assert.ok(s.selected.has("a"));
  s = selectionReducer(s, { type: "range", name: "c", order: ["a", "b", "c"] });
  assert.deepEqual([...s.selected].sort(), ["a", "b", "c"]);
  s = selectionReducer(s, { type: "clear" });
  assert.equal(s.selected.size, 0);
});
```

- [ ] **Step 2: Run — expect FAIL.** `node --experimental-strip-types --test 'src/lib/organize.test.ts'`

- [ ] **Step 3: Implement `organize.ts`**

```ts
// frontend/src/lib/organize.ts
// Pure logic for organizing experiments: tag normalization + autocomplete, star/tag filtering,
// sorting, and the multi-select reducer. No React, so it is unit-tested directly.
const MAX_TAG = 40;
export function normalizeTag(s: string): string { return s.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TAG); }

export function mergeTags(existing: string[], add: string[]): string[] {
  const out: string[] = []; const seen = new Set<string>();
  for (const t of [...existing, ...add].map(normalizeTag)) {
    if (!t) continue; const k = t.toLowerCase(); if (seen.has(k)) continue; seen.add(k); out.push(t);
  }
  return out;
}

type Tagged = { tags?: string[] };
export function tagUniverse(items: readonly Tagged[]): { tag: string; count: number }[] {
  const counts = new Map<string, { tag: string; count: number }>();
  for (const it of items) for (const raw of it.tags ?? []) {
    const t = normalizeTag(raw); if (!t) continue; const k = t.toLowerCase();
    const cur = counts.get(k); if (cur) cur.count += 1; else counts.set(k, { tag: t, count: 1 });
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

export function suggestTags(all: string[], query: string, exclude: string[]): string[] {
  const q = query.trim().toLowerCase();
  const ex = new Set(exclude.map((t) => t.toLowerCase()));
  const freq = tagUniverse(all.map((t) => ({ tags: [t] })));
  return freq.map((f) => f.tag)
    .filter((t) => !ex.has(t.toLowerCase()) && (!q || t.toLowerCase().includes(q)))
    .slice(0, 8);
}

type Exp = { name: string; starred?: boolean; tags?: string[]; started_utc?: string | null; duration_s?: number };
export function filterExperiments<T extends Exp>(items: T[], f: { query: string; starredOnly: boolean; tags: string[] }): T[] {
  const q = f.query.trim().toLowerCase();
  const need = f.tags.map((t) => t.toLowerCase());
  return items.filter((e) => {
    if (f.starredOnly && !e.starred) return false;
    const tags = (e.tags ?? []).map((t) => t.toLowerCase());
    if (need.some((t) => !tags.includes(t))) return false;
    if (!q) return true;
    return e.name.toLowerCase().includes(q) || tags.some((t) => t.includes(q));
  });
}

export type Sort = "newest" | "name" | "duration" | "starred";
export function sortExperiments<T extends Exp>(items: T[], sort: Sort): T[] {
  const newest = (a: T, b: T) => (b.started_utc ?? "").localeCompare(a.started_utc ?? "") || b.name.localeCompare(a.name);
  return [...items].sort((a, b) => {
    if (sort === "name") return a.name.localeCompare(b.name);
    if (sort === "duration") return (b.duration_s ?? 0) - (a.duration_s ?? 0);
    if (sort === "starred") return Number(!!b.starred) - Number(!!a.starred) || newest(a, b);
    return newest(a, b);
  });
}

export type SelectionState = { anchor: string | null; selected: Set<string> };
export type SelectionAction =
  | { type: "toggle"; name: string }
  | { type: "range"; name: string; order: string[] }
  | { type: "selectAll"; names: string[] }
  | { type: "clear" };
export function selectionReducer(s: SelectionState, a: SelectionAction): SelectionState {
  const selected = new Set(s.selected);
  if (a.type === "clear") return { anchor: null, selected: new Set() };
  if (a.type === "selectAll") return { anchor: s.anchor, selected: new Set(a.names) };
  if (a.type === "toggle") {
    selected.has(a.name) ? selected.delete(a.name) : selected.add(a.name);
    return { anchor: a.name, selected };
  }
  // range: select everything between anchor and name in the given order
  const i = a.order.indexOf(s.anchor ?? a.name); const j = a.order.indexOf(a.name);
  if (i >= 0 && j >= 0) for (const n of a.order.slice(Math.min(i, j), Math.max(i, j) + 1)) selected.add(n);
  else selected.add(a.name);
  return { anchor: a.name, selected };
}
```

- [ ] **Step 4: Run — expect PASS.** `npx tsc --noEmit` clean.

- [ ] **Step 5: Commit** `feat(organize): pure tag/star filter, sort, autocomplete, selection logic`.

---

### Task 6: TagPopover component

**Files:**
- Create: `frontend/src/components/TagPopover.tsx`

- [ ] **Step 1** (DOM component — no unit test; verified by tsc + browser): implement a small popover.

```tsx
// frontend/src/components/TagPopover.tsx
import { useState } from "react";
import { normalizeTag, suggestTags } from "../lib/organize.ts";

// Autocomplete tag editor. `tags` are the current tags; `universe` is every tag in use (for
// suggestions). onChange gives the full new tag set. Used for one card and (headless) for bulk add.
export function TagPopover({ tags, universe, onChange, onClose, addOnly = false }: {
  tags: string[]; universe: string[]; onChange: (next: string[]) => void; onClose?: () => void; addOnly?: boolean;
}) {
  const [q, setQ] = useState("");
  const add = (t: string) => { const n = normalizeTag(t); if (!n) return; if (!tags.some((x) => x.toLowerCase() === n.toLowerCase())) onChange([...tags, n]); setQ(""); };
  const remove = (t: string) => onChange(tags.filter((x) => x !== t));
  const sugg = suggestTags(universe, q, tags);
  return (
    <div className="tag-popover" role="dialog" onKeyDown={(e) => { if (e.key === "Escape") onClose?.(); }}>
      {!addOnly && tags.length > 0 && (
        <div className="tag-chips">{tags.map((t) => (
          <span key={t} className="tag-chip">{t}<button aria-label={`remove ${t}`} onClick={() => remove(t)}>×</button></span>
        ))}</div>
      )}
      <input autoFocus type="text" placeholder="add tag…" value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) { e.preventDefault(); add(q); } }} />
      {sugg.length > 0 && (
        <div className="tag-suggest">{sugg.map((t) => (
          <button key={t} className="tag-suggest-item" onClick={() => add(t)}>{t}</button>
        ))}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2:** `npx tsc --noEmit` clean. Commit `feat(ui): TagPopover autocomplete editor`.

---

### Task 7: Card — star, tag chips, popover, selection checkbox

**Files:**
- Modify: `frontend/src/components/ExperimentCard.tsx`

- [ ] **Step 1** (DOM — verified by tsc + browser): extend `Props`:
```ts
interface Props {
  exp: Experiment; onOpen: () => void; onChanged: () => void; driveConnected?: boolean; fullVerify?: boolean;
  universe?: string[];                 // all tags in use, for autocomplete
  selecting?: boolean;                 // selection mode on?
  selected?: boolean;                  // is this card selected?
  onToggleSelect?: (e: React.MouseEvent) => void;  // shift-aware
}
```

- [ ] **Step 2:** add a star toggle + tag chips + `＋` popover. Inside the component:
```tsx
  const [showTags, setShowTags] = useState(false);
  const tags = exp.tags ?? [];
  async function saveLabels(next: { starred?: boolean; tags?: string[] }) {
    const body = { starred: next.starred ?? !!exp.starred, tags: next.tags ?? tags, library: exp.library ?? "local" as const };
    try { await api.setLabels(exp.name, body); onChanged(); } catch (e) { setNote(String(e)); }
  }
```
Render (near the card header): a star button `<button className={`star ${exp.starred ? "on" : ""}`} onClick={(e)=>{e.stopPropagation(); saveLabels({ starred: !exp.starred });}} aria-label="star">★</button>`; the chips row when `tags.length` (each chip `onClick` → a new `onFilterTag?(tag)` prop the page passes); and a `＋` button toggling `showTags` that renders `<TagPopover tags={tags} universe={universe ?? []} onChange={(next)=>saveLabels({ tags: next })} onClose={()=>setShowTags(false)} />`.

When `selecting`, render a checkbox at the corner and make the card's main click call `onToggleSelect` instead of `onOpen` (guard existing click handlers).

- [ ] **Step 3:** `npx tsc --noEmit` clean; commit `feat(ui): star, tags, and select on the experiment card`.

---

### Task 8: ExperimentsPage — filter/sort, selection mode, SelectionBar

**Files:**
- Create: `frontend/src/components/SelectionBar.tsx`
- Modify: `frontend/src/components/ExperimentsPage.tsx`

- [ ] **Step 1: SelectionBar** (floating bar; DOM — tsc + browser):
```tsx
// frontend/src/components/SelectionBar.tsx
export function SelectionBar({ count, driveConnected, busy, progress, onMove, onTag, onStar, onDelete, onSelectAll, onClear }: {
  count: number; driveConnected: boolean; busy: boolean; progress: string | null;
  onMove: (to: "drive" | "local") => void; onTag: () => void; onStar: (on: boolean) => void;
  onDelete: () => void; onSelectAll: () => void; onClear: () => void;
}) {
  return (
    <div className="selection-bar" role="toolbar" aria-label="bulk actions">
      <span>{count} selected</span>
      <button onClick={onSelectAll}>select all</button>
      {driveConnected && <button disabled={busy} onClick={() => onMove("drive")}>move to drive →</button>}
      {driveConnected && <button disabled={busy} onClick={() => onMove("local")}>← local</button>}
      <button disabled={busy} onClick={onTag}>tag…</button>
      <button disabled={busy} onClick={() => onStar(true)}>★ star</button>
      <button disabled={busy} onClick={() => onStar(false)}>☆ unstar</button>
      <button className="danger" disabled={busy} onClick={onDelete}>delete</button>
      {progress && <span className="hint">{progress}</span>}
      <button onClick={onClear}>done</button>
    </div>
  );
}
```

- [ ] **Step 2: Wire the page.** In `ExperimentsPage.tsx`:
  - Replace the ad-hoc filter/sort with `filterExperiments` + `sortExperiments` from `organize.ts`; add state `starredOnly`, `tagFilter: string[]`, and extend the sort union with `"starred"`. Persist filters in `localStorage`. Compute `const universe = useMemo(() => tagUniverse(items ?? []).map(t=>t.tag), [items])`.
  - Header: add a `★ starred` toggle, a `tags ▾` multiselect built from `universe`, active-filter chips (removable), and a **Select** toggle (`selecting`), plus the `starred first` sort option.
  - Selection: `const [sel, dispatch] = useReducer(selectionReducer, { anchor: null, selected: new Set() })`. Pass `selecting`, `selected`, and an `onToggleSelect` (shift → `{type:"range", order: shown.map(e=>e.name)}`, else `{type:"toggle"}`) to each `ExperimentCard`. Pass `universe` and an `onFilterTag` that adds the tag to `tagFilter`.
  - Render `<SelectionBar>` only when `selecting && sel.selected.size > 0`, wired to bulk handlers:
    - **star**: `for (const name of sel.selected) await api.setLabels(name, { starred: on, tags: (byName[name].tags ?? []), library: byName[name].library ?? "local" })`; then `load()`.
    - **tag**: open the shared `TagPopover` in `addOnly` mode; on change, for each selected run `setLabels(name, { starred, tags: mergeTags(existing, chosen), library })`.
    - **move**: sequentially `await api.moveExperiment(name, to, fullVerify)` then poll its `moveStatus` to done/error (reuse the card's poll loop, hoisted to a helper), updating `progress = "moving k/N…"`; collect failures, don't abort; `load()` + `clear` at the end.
    - **delete**: one `window.confirm` listing the count; then `for (...) await api.deleteExperiment(name)`; `load()` + `clear`.
  - After any bulk op, `dispatch({type:"clear"})` and refetch.

- [ ] **Step 3:** `npx tsc --noEmit` clean; frontend tests green.

- [ ] **Step 4: Commit** `feat(ui): star/tag filter + sort and multi-select bulk actions`.

---

### Task 9: Styles (tokens only)

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1:** add `.star`, `.star.on`, `.tag-chip`, `.tag-chips`, `.tag-popover`, `.tag-suggest`, `.tag-suggest-item`, `.selection-bar`, and the selection checkbox styles — using only existing tokens (`--accent`, `--accent-ink`, `--muted`, `--line`, `--line-control`, `--panel`, `--bg-deep`, `--scrim`, `--err`, `--radius`, `--font-mono`). The `.selection-bar` is `position: fixed; bottom: 0` centered, `background: var(--panel)`, `border-top: 1px solid var(--line)`. `.star.on` uses `color: var(--accent)`.

- [ ] **Step 2: Run the theme test** — must stay green (no color literals):
`node --experimental-strip-types --test 'src/lib/theme.test.ts'`

- [ ] **Step 3: Commit** `style: star/tag/selection UI (design tokens only)`.

---

### Task 10: Version bump, full verification, browser check

- [ ] **Step 1:** bump `__version__` (and mirror to `pyproject.toml:3`, `uv.lock:158`).
- [ ] **Step 2:** `uv run --directory backend python -m pytest` (all green) + `ruff check .`; frontend `node --experimental-strip-types --test 'src/**/*.test.ts'` + `npx tsc --noEmit`.
- [ ] **Step 3: Browser verification** against the running operator (`preview_start frontend-dev`): star a run and confirm it persists across reload; add/remove tags via the popover with autocomplete; filter by a tag chip and the `★` toggle; enter selection mode, multi-select (incl. shift-range), and run each bulk action (tag, star, move a small run to the drive and back, delete a throwaway); confirm labels survive the move (check the drive copy shows the tags). Screenshot the selection bar + a tagged card for the user.
- [ ] **Step 4:** commit + push; deploy to the operator (`git pull` in `~/flir-research-interface`, `uv sync --extra dev --inexact`, `launchctl kickstart -k …`).

---

## Self-review notes

- **Spec coverage:** sidecar + normalize (T1), enrich + PUT with `library` (T2), travels-with-move (T3), types/client (T4), all pure logic incl. selection (T5), popover (T6), card star/tags/select (T7), page filter/sort + bulk bar (T8), tokenized styles (T9), verify (T10). All spec sections mapped.
- **Type consistency:** `setLabels(name, {starred, tags, library})` used identically in api.ts, card, and bulk handlers; `Sort` union extended to include `"starred"` in both `organize.ts` and the page; `SelectionState`/`SelectionAction` shared.
- **Careful ordering:** backend is additive and lands first; the page rewire (highest-risk, in-daily-use) is last and fully covered by `organize.ts` unit tests plus a browser pass.
