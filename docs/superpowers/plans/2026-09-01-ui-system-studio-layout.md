# UI System, Studio Layout, Experiment Cards, Reveal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the FLIR Research Interface frontend to the approved "Instrument" visual system in the "Studio" layout, add an Experiments card grid with mid-capture previews and hover-scrub keyframes, and add a reveal-in-file-manager action served by the local operator.

**Architecture:** Frontend (Vite + React + TypeScript in `frontend/`) gets a token file, self-hosted IBM Plex fonts, a layout-state reducer, and Studio shell components (`ToolStrip`, `Rail`, `PlotDock`, `StatusBar`) that wrap the existing `ThermalView`, `DisplayControls`, `RecordPanel`, `SetupPage`, `PlaybackPage`. Backend (`backend/flir_research_interface`) gains a preview renderer (`analysis/preview.py`) invoked at recorder finalize plus on demand, preview/keyframe endpoints, and a path-contained reveal endpoint. All rendering products are visualization only and never touch the Zarr store.

**Tech Stack:** Python 3.12, FastAPI, numpy, zarr 2, Pillow (new); React 18, TypeScript 5, Vite 5, Node 23 built-in test runner (`node --experimental-strip-types --test`).

**Conventions used below**
- Backend commands run from `backend/` with the project venv: `.venv/bin/pytest -p no:warnings`, `.venv/bin/ruff check .`, `.venv/bin/ruff format .`, `.venv/bin/mypy flir_research_interface`.
- Frontend commands run from `frontend/`: `npm test`, `npm run build`.
- Commit with `git -c user.name="Matthew McCoy" -c user.email="mmac32s1@gmail.com" commit -m "..."` from the repo root. Every commit message ends with the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Browser verification: the operator serves `frontend/dist` at `http://localhost:8000` (`uv run fri-serve` from `backend/`, or the `backend` entry in `.claude/launch.json`). After `npm run build`, reload the page; restart the server only when backend code changed.

---

## File structure

**Frontend (create)**
- `frontend/public/fonts/` — IBM Plex Sans (400/500/600) and IBM Plex Mono (400/500/600) woff2 files, fetched once by `scripts/fetch_fonts.sh`.
- `frontend/src/theme.css` — all design tokens and `@font-face` rules. The only place colours are defined.
- `frontend/src/lib/layout.ts` — layout state (strip/rail/dock collapsed, rail section open flags, active tool) with a pure reducer and `localStorage` persistence.
- `frontend/src/lib/keyframes.ts` — pure helpers for hover-scrub (mouse x → keyframe index, label).
- `frontend/src/components/studio/ToolStrip.tsx`, `Rail.tsx`, `RailSection.tsx`, `PlotDock.tsx`, `StatusBar.tsx`, `StudioFrame.tsx` — the Studio shell.
- `frontend/src/components/ExperimentCard.tsx` — card with preview, keyframe scrub, actions.
- `frontend/src/lib/layout.test.ts`, `frontend/src/lib/keyframes.test.ts`, `frontend/src/lib/theme.test.ts`.

**Frontend (modify)**
- `frontend/src/styles.css` → becomes component styles that consume tokens (no raw colours).
- `frontend/src/App.tsx` → uses `StudioFrame`; keeps page routing.
- `frontend/src/components/ExperimentsPage.tsx` → card grid.
- `frontend/src/components/PlaybackPage.tsx` → renders inside `StudioFrame` with transport in the status bar.
- `frontend/src/lib/api.ts` → `reveal`, `revealRoot`, preview URL helpers.
- `frontend/index.html` → title, no external font links.

**Backend (create)**
- `backend/flir_research_interface/analysis/preview.py` — iron palette LUT, `render_png`, `render_preview`, `render_keyframes`, `generate_previews(exp_dir)`.
- `backend/flir_research_interface/api/reveal.py` — `reveal_command(system, path)`, `contained(root, path)`, `reveal(path, runner)`.
- `backend/flir_research_interface/thumbs.py` — `fri-thumbs` CLI to (re)generate previews for existing experiments.
- Tests: `backend/tests/test_preview.py`, `backend/tests/test_reveal.py`, `backend/tests/test_api_previews.py`.

**Backend (modify)**
- `backend/flir_research_interface/recording/recorder.py` — call preview generation in `_write_manifest`, record `previews` in the manifest.
- `backend/flir_research_interface/playback/reader.py` — `info()` exposes `previews`.
- `backend/flir_research_interface/api/app.py` — preview/keyframe/reveal endpoints.
- `backend/pyproject.toml` — add `pillow`, `fri-thumbs` script.

---

## Task 1: Design tokens and self-hosted fonts

**Files:**
- Create: `scripts/fetch_fonts.sh`, `frontend/src/theme.css`, `frontend/src/lib/theme.test.ts`
- Modify: `frontend/index.html`, `frontend/src/main.tsx`, `frontend/package.json` (test glob unchanged; theme test reads the css file)

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/theme.test.ts`

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "..", "theme.css"), "utf8");

const REQUIRED = [
  "--bg", "--bg-deep", "--panel", "--line", "--fg", "--fg-strong", "--muted",
  "--accent", "--live", "--err", "--rec", "--font-ui", "--font-mono",
];

test("theme.css defines every token from the spec on :root", () => {
  for (const t of REQUIRED) assert.match(css, new RegExp(`${t}\\s*:`), `${t} missing`);
});

test("theme.css self-hosts IBM Plex (no Google Fonts URLs)", () => {
  assert.match(css, /@font-face[^}]*IBM Plex Sans/);
  assert.match(css, /@font-face[^}]*IBM Plex Mono/);
  assert.doesNotMatch(css, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});

test("live green and accent amber are the spec values", () => {
  assert.match(css, /--live:\s*#5cff8a/i);
  assert.match(css, /--accent:\s*#ffb454/i);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test`
Expected: `theme.test.ts` fails with `ENOENT ... theme.css`.

- [ ] **Step 3: Fetch the fonts** — create `scripts/fetch_fonts.sh` and run it once

```bash
#!/usr/bin/env bash
# Downloads IBM Plex Sans/Mono woff2 (latin subset) from Google Fonts into frontend/public/fonts.
# Run once; the files are committed so builds and offline mode need no network.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/.." && pwd)/frontend/public/fonts"
mkdir -p "$OUT"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15"
fetch() { # family weight outfile
  css=$(curl -sL -A "$UA" "https://fonts.googleapis.com/css2?family=$1:wght@$2&display=swap")
  url=$(printf '%s' "$css" | grep -o 'https://fonts.gstatic.com/[^)]*\.woff2' | head -1)
  [ -n "$url" ] || { echo "no woff2 url for $1 $2" >&2; exit 1; }
  curl -sL "$url" -o "$OUT/$3"; echo "$3 <- $url"
}
fetch "IBM+Plex+Sans" 400 IBMPlexSans-400.woff2
fetch "IBM+Plex+Sans" 500 IBMPlexSans-500.woff2
fetch "IBM+Plex+Sans" 600 IBMPlexSans-600.woff2
fetch "IBM+Plex+Mono" 400 IBMPlexMono-400.woff2
fetch "IBM+Plex+Mono" 500 IBMPlexMono-500.woff2
fetch "IBM+Plex+Mono" 600 IBMPlexMono-600.woff2
ls -la "$OUT"
```

Run: `chmod +x scripts/fetch_fonts.sh && scripts/fetch_fonts.sh`
Expected: six `.woff2` files listed, each 10–40 kB. (IBM Plex is OFL-licensed; add `frontend/public/fonts/OFL.txt` with the license text from https://github.com/IBM/plex/blob/master/LICENSE.txt.)

- [ ] **Step 4: Write `frontend/src/theme.css`**

```css
/* FLIR Research Interface — design tokens (spec §2). The ONLY place colours are defined. */
@font-face { font-family: "IBM Plex Sans"; font-weight: 400; font-display: swap; src: url("/fonts/IBMPlexSans-400.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 500; font-display: swap; src: url("/fonts/IBMPlexSans-500.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 600; font-display: swap; src: url("/fonts/IBMPlexSans-600.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 400; font-display: swap; src: url("/fonts/IBMPlexMono-400.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 500; font-display: swap; src: url("/fonts/IBMPlexMono-500.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 600; font-display: swap; src: url("/fonts/IBMPlexMono-600.woff2") format("woff2"); }

:root {
  color-scheme: dark;
  --bg: #101418;
  --bg-deep: #0b0e12;
  --panel: #141920;
  --line: #232a33;
  --line-strong: #2f3843;
  --fg: #d7dde5;
  --fg-strong: #f5f7fa;
  --muted: #8b97a5;
  --accent: #ffb454;
  --accent-ink: #101418;
  --live: #5cff8a;
  --live-glow: 0 0 8px rgba(92, 255, 138, 0.7);
  --warn: #ffb454;
  --warn-bg: rgba(255, 180, 84, 0.10);
  --err: #ff5f56;
  --err-bg: rgba(255, 95, 86, 0.12);
  --rec: #ff5f56;
  --font-ui: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --fs: 13px;
  --space: 4px;
  --radius: 3px;
  --strip-w: 40px;
  --rail-w: 300px;
  --dock-h: 220px;
  --topbar-h: 40px;
  --statusbar-h: 28px;
}

@keyframes fri-glow { 0%, 100% { box-shadow: var(--live-glow); } 50% { box-shadow: 0 0 3px rgba(92, 255, 138, 0.4); } }
@keyframes fri-blink { 0%, 60% { opacity: 1; } 61%, 100% { opacity: 0.25; } }
```

- [ ] **Step 5: Wire it in** — `frontend/src/main.tsx` import order and `frontend/index.html`

`main.tsx`: replace `import "./styles.css";` with
```ts
import "./theme.css";
import "./styles.css";
```

`index.html`: ensure `<title>FLIR Research Interface</title>` and no `<link>` to Google Fonts (there is none today; keep it that way).

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npm test`
Expected: all pass, including 3 theme tests (`ℹ pass 19`).

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_fonts.sh frontend/public/fonts frontend/src/theme.css frontend/src/lib/theme.test.ts frontend/src/main.tsx
git commit -m "feat(ui): design tokens and self-hosted IBM Plex fonts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 2: Layout state reducer with persistence

**Files:**
- Create: `frontend/src/lib/layout.ts`, `frontend/src/lib/layout.test.ts`

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/layout.test.ts`

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout, type LayoutState } from "./layout.ts";

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(), key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k),
  } as Storage;
}

test("defaults: strip and rail open, dock open, all rail sections open, tool select", () => {
  assert.equal(DEFAULT_LAYOUT.strip, true);
  assert.equal(DEFAULT_LAYOUT.rail, true);
  assert.equal(DEFAULT_LAYOUT.dock, true);
  assert.equal(DEFAULT_LAYOUT.tool, "select");
  assert.deepEqual(Object.values(DEFAULT_LAYOUT.sections).every(Boolean), true);
});

test("toggle actions flip one flag and leave the rest", () => {
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "toggle", panel: "rail" });
  assert.equal(s1.rail, false); assert.equal(s1.strip, true); assert.equal(s1.dock, true);
  const s2 = layoutReducer(s1, { type: "toggleSection", section: "camera" });
  assert.equal(s2.sections.camera, false); assert.equal(s2.sections.measurements, true);
});

test("setTool changes the active tool", () => {
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setTool", tool: "rect" }).tool, "rect");
});

test("collapseAll hides strip, rail and dock; restore brings them back", () => {
  const c = layoutReducer(DEFAULT_LAYOUT, { type: "collapseAll" });
  assert.deepEqual([c.strip, c.rail, c.dock], [false, false, false]);
  const r = layoutReducer(c, { type: "restoreAll" });
  assert.deepEqual([r.strip, r.rail, r.dock], [true, true, true]);
});

test("save/load round-trips and ignores corrupt storage", () => {
  const st = memStorage();
  const s: LayoutState = { ...DEFAULT_LAYOUT, rail: false, tool: "spot" };
  saveLayout(st, s);
  assert.deepEqual(loadLayout(st), s);
  st.setItem("fri.layout.v1", "{not json");
  assert.deepEqual(loadLayout(st), DEFAULT_LAYOUT);
  assert.deepEqual(loadLayout(null), DEFAULT_LAYOUT);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test`
Expected: `layout.test.ts` fails: cannot find module `./layout.ts`.

- [ ] **Step 3: Implement `frontend/src/lib/layout.ts`**

```ts
/** Studio layout state (spec §3): which panels are open, which rail sections, which tool. */
export type Tool = "select" | "spot" | "rect" | "line" | "display" | "camera" | "nuc";
export type Panel = "strip" | "rail" | "dock";
export type Section = "measurements" | "camera" | "experiment" | "recording" | "display";

export interface LayoutState {
  strip: boolean;
  rail: boolean;
  dock: boolean;
  tool: Tool;
  sections: Record<Section, boolean>;
}

export const DEFAULT_LAYOUT: LayoutState = {
  strip: true,
  rail: true,
  dock: true,
  tool: "select",
  sections: { measurements: true, camera: true, experiment: true, recording: true, display: true },
};

export type LayoutAction =
  | { type: "toggle"; panel: Panel }
  | { type: "toggleSection"; section: Section }
  | { type: "setTool"; tool: Tool }
  | { type: "collapseAll" }
  | { type: "restoreAll" };

export function layoutReducer(s: LayoutState, a: LayoutAction): LayoutState {
  switch (a.type) {
    case "toggle": return { ...s, [a.panel]: !s[a.panel] };
    case "toggleSection": return { ...s, sections: { ...s.sections, [a.section]: !s.sections[a.section] } };
    case "setTool": return { ...s, tool: a.tool };
    case "collapseAll": return { ...s, strip: false, rail: false, dock: false };
    case "restoreAll": return { ...s, strip: true, rail: true, dock: true };
  }
}

const KEY = "fri.layout.v1";

export function loadLayout(storage: Storage | null): LayoutState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<LayoutState>;
    return {
      ...DEFAULT_LAYOUT,
      ...parsed,
      sections: { ...DEFAULT_LAYOUT.sections, ...(parsed.sections ?? {}) },
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function saveLayout(storage: Storage | null, s: LayoutState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable: ignore */ }
}
```

- [ ] **Step 4: Run tests** — `npm test` → all pass (`ℹ pass 24`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/layout.ts frontend/src/lib/layout.test.ts
git commit -m "feat(ui): layout state reducer with localStorage persistence

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 3: Studio shell components

**Files:**
- Create: `frontend/src/components/studio/ToolStrip.tsx`, `RailSection.tsx`, `Rail.tsx`, `PlotDock.tsx`, `StatusBar.tsx`, `StudioFrame.tsx`
- Modify: `frontend/src/styles.css` (replace entirely)

This task is UI/DOM: no unit test. Verification is the browser check in Step 8.

- [ ] **Step 1: Replace `frontend/src/styles.css`** with token-driven component styles

```css
* { box-sizing: border-box; }
html, body, #root { height: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: var(--font-ui); font-size: var(--fs); line-height: 1.35; }
code, .mono, .v, .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
button, select, input { font: inherit; }

/* ---- Studio frame -------------------------------------------------------- */
.studio { display: grid; height: 100vh; grid-template-rows: var(--topbar-h) minmax(0, 1fr) var(--statusbar-h);
  grid-template-columns: var(--strip-w) minmax(0, 1fr) var(--rail-w);
  grid-template-areas: "top top top" "strip center rail" "status status status"; }
.studio.no-strip { grid-template-columns: 0 minmax(0, 1fr) var(--rail-w); }
.studio.no-rail { grid-template-columns: var(--strip-w) minmax(0, 1fr) 0; }
.studio.no-strip.no-rail { grid-template-columns: 0 minmax(0, 1fr) 0; }
.studio > .topbar { grid-area: top; }
.studio > .strip { grid-area: strip; }
.studio > .center { grid-area: center; display: grid; grid-template-rows: minmax(0, 1fr) var(--dock-h); min-width: 0; min-height: 0; }
.studio.no-dock > .center { grid-template-rows: minmax(0, 1fr) 0; }
.studio > .rail { grid-area: rail; }
.studio > .statusbar { grid-area: status; }
.studio.page > .center { grid-template-rows: minmax(0, 1fr); }   /* non-image pages: no dock */

/* ---- Top bar --------------------------------------------------------------- */
.topbar { display: flex; align-items: center; gap: 18px; padding: 0 14px; background: var(--bg-deep); border-bottom: 1px solid var(--line); }
.wordmark { font-family: var(--font-mono); font-weight: 600; letter-spacing: 0.12em; color: var(--fg-strong); font-size: 12px; white-space: nowrap; }
.tabs { display: flex; gap: 2px; }
.tabs button { background: none; border: none; color: var(--muted); padding: 10px 10px; cursor: pointer; border-bottom: 2px solid transparent; font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.04em; }
.tabs button.active { color: var(--fg-strong); border-bottom-color: var(--accent); }
.conn { margin-left: auto; display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 12px; color: var(--muted); }
.conn .who { color: var(--fg); }

/* ---- Status dot semantics (spec §2): green only when frames are arriving ------ */
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: var(--line-strong); }
.dot.live { background: var(--live); animation: fri-glow 2s ease-in-out infinite; }
.dot.warn { background: var(--warn); }
.dot.err { background: var(--err); }

/* ---- Buttons / inputs ------------------------------------------------------ */
button.primary { background: var(--accent); color: var(--accent-ink); border: none; padding: 6px 12px; border-radius: var(--radius); cursor: pointer; font-weight: 600; font-family: var(--font-mono); font-size: 12px; }
button.secondary { background: transparent; color: var(--fg); border: 1px solid var(--line-strong); padding: 5px 10px; border-radius: var(--radius); cursor: pointer; font-family: var(--font-mono); font-size: 12px; }
button.danger { background: var(--err); color: #fff; border: none; padding: 6px 12px; border-radius: var(--radius); cursor: pointer; font-weight: 600; font-family: var(--font-mono); font-size: 12px; }
button:disabled { opacity: 0.45; cursor: default; }
select, input[type=number], input[type=text] { background: var(--bg-deep); color: var(--fg); border: 1px solid var(--line-strong); border-radius: var(--radius); padding: 4px 6px; font-family: var(--font-mono); font-size: 12px; }
input[type=number] { width: 84px; }
input[type=range] { accent-color: var(--accent); }

/* ---- Tool strip -------------------------------------------------------------- */
.strip { background: var(--bg-deep); border-right: 1px solid var(--line); display: flex; flex-direction: column; align-items: center; padding-top: 8px; gap: 6px; overflow: hidden; }
.strip button { width: 28px; height: 28px; border-radius: var(--radius); border: 1px solid var(--line-strong); background: transparent; color: var(--fg); cursor: pointer; font-family: var(--font-mono); font-size: 12px; display: grid; place-items: center; }
.strip button.active { border-color: var(--accent); color: var(--accent); background: var(--warn-bg); }
.strip button:disabled { opacity: 0.35; }
.strip .spacer { flex: 1; }

/* ---- Center / image ---------------------------------------------------------- */
.view { position: relative; display: flex; flex: 1; align-items: center; justify-content: center; background: #000; min-width: 0; min-height: 0; }
.view canvas { max-width: 100%; max-height: 100%; image-rendering: pixelated; }
.readout { position: absolute; left: 12px; top: 12px; background: rgba(11, 14, 18, 0.85); padding: 6px 10px; border-left: 2px solid var(--accent); color: var(--accent); font-family: var(--font-mono); font-size: 12px; white-space: pre; }

/* ---- Plot dock ----------------------------------------------------------------- */
.dock { background: var(--bg-deep); border-top: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.dock .dock-head { display: flex; align-items: center; gap: 10px; padding: 4px 10px; color: var(--muted); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; border-bottom: 1px solid var(--line); }
.dock .dock-body { flex: 1; display: grid; place-items: center; color: var(--muted); font-family: var(--font-mono); font-size: 12px; }

/* ---- Rail ---------------------------------------------------------------------- */
.rail { background: var(--panel); border-left: 1px solid var(--line); overflow-y: auto; overflow-x: hidden; }
.rail-section { border-bottom: 1px solid var(--line); }
.rail-section > header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; cursor: pointer; user-select: none; color: var(--muted); font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; }
.rail-section > header .chev { margin-left: auto; opacity: 0.7; }
.rail-section > header .tag { color: var(--muted); letter-spacing: 0; text-transform: none; font-size: 10px; border: 1px solid var(--line-strong); padding: 0 4px; border-radius: 2px; }
.rail-section > .body { padding: 4px 12px 12px; display: flex; flex-direction: column; gap: 8px; }
.kv { display: grid; grid-template-columns: 1fr auto; gap: 3px 12px; align-items: baseline; }
.kv .v { text-align: right; color: var(--accent); }
.kv .v.plain { color: var(--fg); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.badge { padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; font-family: var(--font-mono); }
.badge.auto { background: rgba(92, 255, 138, 0.12); color: var(--live); }
.badge.manual { background: var(--warn-bg); color: var(--warn); }
.badge.rec { background: var(--err-bg); color: var(--rec); animation: fri-blink 1s steps(1) infinite; }
.warnbox { border-left: 3px solid var(--warn); padding: 6px 10px; background: var(--warn-bg); font-size: 12px; }
.errbox { border-left: 3px solid var(--err); padding: 6px 10px; background: var(--err-bg); font-size: 12px; }
.muted { color: var(--muted); }
.colorbar { display: flex; align-items: center; gap: 8px; }
.colorbar canvas { flex: 1 1 auto; min-width: 0; height: 12px; border: 1px solid var(--line); }
.colorbar span { white-space: nowrap; font-family: var(--font-mono); font-size: 11px; }

/* ---- Status bar --------------------------------------------------------------- */
.statusbar { display: flex; align-items: center; gap: 18px; padding: 0 14px; background: var(--bg-deep); border-top: 1px solid var(--line); font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
.statusbar b { color: var(--fg); font-weight: 500; }
.statusbar .bad { color: var(--err); }
.statusbar .warnv { color: var(--warn); }
.statusbar .right { margin-left: auto; display: flex; gap: 18px; }

/* ---- Pages (setup, experiments) ------------------------------------------------- */
.page-body { padding: 20px; overflow: auto; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; margin-bottom: 14px; }
.card h2 { margin: 0 0 10px; font-size: 13px; font-family: var(--font-mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
pre { background: var(--bg-deep); border: 1px solid var(--line); padding: 8px; border-radius: var(--radius); overflow: auto; font-size: 12px; }

/* ---- Experiment cards (Task 8) --------------------------------------------------- */
.exp-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; font-family: var(--font-mono); font-size: 12px; color: var(--muted); }
.exp-head .right { margin-left: auto; display: flex; gap: 8px; }
.exp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.exp-card { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; display: flex; flex-direction: column; }
.exp-card .thumb { position: relative; aspect-ratio: 4 / 3; background: #000; overflow: hidden; cursor: crosshair; }
.exp-card .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.exp-card .thumb .kf { position: absolute; inset: 0; background-repeat: no-repeat; background-size: 1200% 100%; }
.exp-card .thumb .t { position: absolute; left: 6px; bottom: 6px; background: rgba(11, 14, 18, 0.85); color: var(--accent); padding: 2px 6px; font-family: var(--font-mono); font-size: 11px; }
.exp-card .thumb .ph { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-family: var(--font-mono); font-size: 11px; }
.exp-card .body { padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.exp-card .name { color: var(--fg-strong); font-family: var(--font-mono); font-size: 12px; word-break: break-all; }
.exp-card .meta { display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-family: var(--font-mono); font-size: 11px; }
.exp-card .actions { display: flex; gap: 6px; margin-top: auto; }
.badge.ok { background: rgba(92, 255, 138, 0.12); color: var(--live); }
.badge.bad { background: var(--err-bg); color: var(--err); }
```

- [ ] **Step 2: Create `frontend/src/components/studio/RailSection.tsx`**

```tsx
import type { ReactNode } from "react";

interface Props { title: string; open: boolean; onToggle: () => void; tag?: string; children: ReactNode; }

export function RailSection({ title, open, onToggle, tag, children }: Props) {
  return (
    <section className="rail-section">
      <header onClick={onToggle} role="button" aria-expanded={open}>
        <span>{title}</span>
        {tag && <span className="tag">{tag}</span>}
        <span className="chev">{open ? "▾" : "▸"}</span>
      </header>
      {open && <div className="body">{children}</div>}
    </section>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/studio/ToolStrip.tsx`**

```tsx
import type { Tool } from "../../lib/layout.ts";

const TOOLS: { id: Tool; glyph: string; title: string; enabled: boolean }[] = [
  { id: "select", glyph: "↖", title: "Select / hover readout", enabled: true },
  { id: "spot", glyph: "◎", title: "Spot (Milestone 6)", enabled: false },
  { id: "rect", glyph: "▭", title: "Rectangle ROI (Milestone 6)", enabled: false },
  { id: "line", glyph: "╱", title: "Line profile (later)", enabled: false },
  { id: "display", glyph: "▤", title: "Palette & range", enabled: true },
  { id: "camera", glyph: "⚙", title: "Camera controls (Milestone 6)", enabled: false },
  { id: "nuc", glyph: "N", title: "NUC (Milestone 6)", enabled: false },
];

interface Props { tool: Tool; onTool: (t: Tool) => void; onCollapseAll: () => void; }

/** Left icon strip (spec §3). Disabled tools stay visible so the layout never shifts between releases. */
export function ToolStrip({ tool, onTool, onCollapseAll }: Props) {
  return (
    <nav className="strip" aria-label="tools">
      {TOOLS.map((t) => (
        <button key={t.id} className={tool === t.id ? "active" : ""} title={t.title} disabled={!t.enabled} onClick={() => onTool(t.id)}>
          {t.glyph}
        </button>
      ))}
      <span className="spacer" />
      <button title="Hide panels (image only)" onClick={onCollapseAll}>⛶</button>
    </nav>
  );
}
```

- [ ] **Step 4: Create `frontend/src/components/studio/PlotDock.tsx`** (placeholder until Milestone 6)

```tsx
interface Props { title?: string; onCollapse: () => void; children?: React.ReactNode; }

export function PlotDock({ title = "temperature vs time", onCollapse, children }: Props) {
  return (
    <div className="dock">
      <div className="dock-head">
        <span>{title}</span>
        <button className="secondary" style={{ marginLeft: "auto", padding: "0 6px" }} onClick={onCollapse} title="Collapse dock">▾</button>
      </div>
      <div className="dock-body">{children ?? <span>plots arrive with ROIs (Milestone 6)</span>}</div>
    </div>
  );
}
```

- [ ] **Step 5: Create `frontend/src/components/studio/StatusBar.tsx`**

```tsx
import type { ReactNode } from "react";
import type { RecordingStatus, Status } from "../../lib/api.ts";

interface Props { status: Status; recording: RecordingStatus | null; displayFps: number; stale: boolean; left?: ReactNode; }

function num(v: number | null | undefined, d = 1): string { return v == null ? "—" : v.toFixed(d); }

/** Bottom status bar (spec §3). Never shows green; drops are red, gaps amber. */
export function StatusBar({ status, recording, displayFps, stale, left }: Props) {
  const rec = recording?.state === "recording";
  return (
    <footer className="statusbar">
      {left}
      <span>cam <b>{num(status.camera_fps)}</b> fps</span>
      <span>disp <b>{num(displayFps)}</b> fps</span>
      <span>rx <b>{status.frames_received ?? 0}</b></span>
      <span>viz-drop <b>{status.viz_dropped ?? 0}</b></span>
      {rec && (
        <>
          <span className={(recording?.queue_dropped ?? 0) > 0 ? "bad" : ""}>rec-drop <b>{recording?.queue_dropped ?? 0}</b></span>
          <span className={(recording?.frame_id_gaps ?? 0) > 0 ? "warnv" : ""}>gaps <b>{recording?.frame_id_gaps ?? 0}</b></span>
        </>
      )}
      {stale && <span className="bad">NO FRAMES</span>}
      <span className="right">
        {rec && <span className="badge rec">● REC {num(recording?.duration_s, 0)} s</span>}
        <span className={(recording?.free_space_gb ?? Infinity) < 5 ? "bad" : ""}>disk <b>{num(recording?.free_space_gb)}</b> GB</span>
      </span>
    </footer>
  );
}
```

- [ ] **Step 6: Create `frontend/src/components/studio/Rail.tsx`**

```tsx
import type { ReactNode } from "react";

/** Right rail container; sections are passed as children (RailSection). */
export function Rail({ children }: { children: ReactNode }) {
  return <aside className="rail">{children}</aside>;
}
```

- [ ] **Step 7: Create `frontend/src/components/studio/StudioFrame.tsx`**

```tsx
import type { ReactNode } from "react";
import type { LayoutState } from "../../lib/layout.ts";

interface Props {
  layout: LayoutState;
  /** true for setup/experiments pages: center spans full height, no dock, strip hidden */
  page?: boolean;
  topbar: ReactNode;
  strip?: ReactNode;
  center: ReactNode;
  dock?: ReactNode;
  rail?: ReactNode;
  statusbar: ReactNode;
}

/** The Studio grid (spec §3). Panels collapse via layout flags; grid areas are fixed. */
export function StudioFrame({ layout, page = false, topbar, strip, center, dock, rail, statusbar }: Props) {
  const cls = ["studio", page ? "page no-strip" : "", !page && !layout.strip ? "no-strip" : "",
    !layout.rail || !rail ? "no-rail" : "", !layout.dock || !dock ? "no-dock" : ""].filter(Boolean).join(" ");
  return (
    <div className={cls}>
      <div className="topbar">{topbar}</div>
      {!page && layout.strip && strip}
      <div className="center">
        {center}
        {!page && layout.dock && dock}
      </div>
      {layout.rail && rail}
      <div className="statusbar-slot" style={{ display: "contents" }}>{statusbar}</div>
    </div>
  );
}
```

Note: `StatusBar` renders a `<footer className="statusbar">`, which is what the grid area targets; the `display: contents` wrapper keeps it a direct grid child.

- [ ] **Step 8: Type-check only** (App is wired in Task 4)

Run: `cd frontend && npx tsc -p tsconfig.json --noEmit`
Expected: no errors (unused-file warnings do not apply; components are not yet imported).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/styles.css frontend/src/components/studio
git commit -m "feat(ui): Studio shell components and token-driven styles

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 4: Wire App, live view and existing panels into the Studio frame

**Files:**
- Modify: `frontend/src/App.tsx` (replace), `frontend/src/components/DisplayControls.tsx`, `frontend/src/components/RecordPanel.tsx`, `frontend/src/components/SetupPage.tsx`, `frontend/src/components/ThermalView.tsx`

- [ ] **Step 1: Replace `frontend/src/App.tsx`**

```tsx
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, type RecordingStatus, type Status } from "./lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "./lib/protocol.ts";
import type { PaletteName } from "./lib/palette.ts";
import type { Range, ScaleMode } from "./lib/scale.ts";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout } from "./lib/layout.ts";
import { ThermalView } from "./components/ThermalView.tsx";
import { DisplayControls } from "./components/DisplayControls.tsx";
import { SetupPage } from "./components/SetupPage.tsx";
import { RecordPanel } from "./components/RecordPanel.tsx";
import { ExperimentsPage } from "./components/ExperimentsPage.tsx";
import { PlaybackPage } from "./components/PlaybackPage.tsx";
import { StudioFrame } from "./components/studio/StudioFrame.tsx";
import { ToolStrip } from "./components/studio/ToolStrip.tsx";
import { Rail } from "./components/studio/Rail.tsx";
import { RailSection } from "./components/studio/RailSection.tsx";
import { PlotDock } from "./components/studio/PlotDock.tsx";
import { StatusBar } from "./components/studio/StatusBar.tsx";

type Page = "live" | "setup" | "experiments" | "playback";
const storage = typeof localStorage !== "undefined" ? localStorage : null;

export function App() {
  const [page, setPage] = useState<Page>("setup");
  const [openExp, setOpenExp] = useState<string | null>(null);
  const [layout, dispatch] = useReducer(layoutReducer, DEFAULT_LAYOUT, () => loadLayout(storage));
  useEffect(() => saveLayout(storage, layout), [layout]);

  const [status, setStatus] = useState<Status>({ state: "disconnected" });
  const [recording, setRecording] = useState<RecordingStatus | null>(null);
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [palette, setPalette] = useState<PaletteName>("iron");
  const [scaleMode, setScaleMode] = useState<ScaleMode>("auto");
  const [manual, setManual] = useState<Range>({ min: 20, max: 40 });
  const [shown, setShown] = useState<Range>({ min: 0, max: 100 });
  const [wsFps, setWsFps] = useState(0);
  const [lastFrameAt, setLastFrameAt] = useState(0);
  const fpsCounter = useRef({ n: 0, t: performance.now() });
  const info = useRef<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    try { setStatus(await api.status()); } catch { setStatus({ state: "unreachable" }); }
    try { setRecording(await api.recordingStatus()); } catch { /* keep last */ }
  }, []);
  useEffect(() => { void refresh(); const id = setInterval(refresh, 1000); return () => clearInterval(id); }, [refresh]);

  useEffect(() => {
    if (status.state !== "acquiring") return;
    let alive = true;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/frames`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (ev) => {
      if (!alive || typeof ev.data === "string") return;
      try {
        setFrame(decodeFrameMessage(ev.data as ArrayBuffer));
        setLastFrameAt(performance.now());
        const c = fpsCounter.current; c.n += 1;
        const dt = performance.now() - c.t;
        if (dt >= 1000) { setWsFps((c.n * 1000) / dt); c.n = 0; c.t = performance.now(); }
      } catch (e) { console.error(e); }
    };
    api.info().then((i) => { info.current = i; }).catch(() => undefined);
    return () => { alive = false; ws.close(); };
  }, [status.state]);

  const stale = status.state === "acquiring" && lastFrameAt > 0 && performance.now() - lastFrameAt > 2000;
  const dot = status.state === "acquiring" && !stale ? "live" : status.state === "error" ? "err"
    : status.state === "disconnected" ? "" : "warn";

  async function disconnect() { await api.disconnect(); setFrame(null); await refresh(); setPage("setup"); }

  const hdr = frame?.header;
  const cam = info.current ?? {};
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;
  const obj = cam.object_parameters as Record<string, unknown> | undefined;
  const nearLimit = hdr && active && hdr.max_c != null && active.high_c != null && hdr.max_c > active.high_c - 10;

  const topbar = (
    <>
      <span className="wordmark">FLIR RESEARCH INTERFACE</span>
      <nav className="tabs">
        <button className={page === "live" ? "active" : ""} onClick={() => setPage("live")}>live</button>
        <button className={page === "experiments" || page === "playback" ? "active" : ""} onClick={() => setPage("experiments")}>experiments</button>
        <button className={page === "setup" ? "active" : ""} onClick={() => setPage("setup")}>setup</button>
      </nav>
      <span className="conn">
        <span className={`dot ${dot}`} />
        <span className="who">{status.device ? `${status.device.model} · ${status.device.serial}` : "no camera"}</span>
        <span>· {stale ? "no frames" : status.state}</span>
        {status.state !== "disconnected" && status.state !== "unreachable" && <button className="secondary" onClick={disconnect}>disconnect</button>}
      </span>
    </>
  );

  const statusbar = <StatusBar status={status} recording={recording} displayFps={wsFps} stale={stale} />;

  if (page === "setup") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<SetupPage onConnected={() => { void refresh(); setPage("live"); }} />} />;
  }
  if (page === "experiments") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<ExperimentsPage onOpen={(name) => { setOpenExp(name); setPage("playback"); }} />} />;
  }
  if (page === "playback" && openExp) {
    return <PlaybackPage name={openExp} layout={layout} dispatch={dispatch} topbar={topbar}
      palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode}
      manual={manual} setManual={setManual} onBack={() => setPage("experiments")} status={status} recording={recording} />;
  }

  return (
    <StudioFrame layout={layout} topbar={topbar} statusbar={statusbar}
      strip={<ToolStrip tool={layout.tool} onTool={(t) => dispatch({ type: "setTool", tool: t })} onCollapseAll={() => dispatch({ type: "collapseAll" })} />}
      center={<ThermalView frame={frame} palette={palette} scaleMode={scaleMode} manual={manual} onScale={setShown} />}
      dock={<PlotDock onCollapse={() => dispatch({ type: "toggle", panel: "dock" })} />}
      rail={
        <Rail>
          <RailSection title="measurements" open={layout.sections.measurements} onToggle={() => dispatch({ type: "toggleSection", section: "measurements" })}>
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmt(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmt(hdr.min_c)}</span>
                <span>max</span><span className="v">{fmt(hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmt(hdr.mean_c)}</span>
                <span>ir format</span><span className="v plain">{hdr.ir_format}</span>
                <span>frame</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">waiting for frames…</div>}
            {hdr && hdr.kelvin_per_count === null && <div className="errbox">Stream is not temperature-linear; raw counts only.</div>}
            {nearLimit && <div className="warnbox">Max within 10 °C of the range limit ({active?.high_c} °C).</div>}
          </RailSection>
          <RailSection title="camera" open={layout.sections.camera} onToggle={() => dispatch({ type: "toggleSection", section: "camera" })} tag="read-only until M6">
            <div className="kv">
              <span>case</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              <span>emissivity</span><span className="v">{fmtAny(obj?.ObjectEmissivity)}</span>
              <span>T reflected</span><span className="v">{kelvin(obj?.ReflectedTemperature)}</span>
              <span>distance</span><span className="v">{fmtAny(obj?.ObjectDistance)} m</span>
              <span>NUC</span><span className="v plain">{fmtAny(cam.nuc_mode)}</span>
              <span>lens</span><span className="v plain">{fmtAny(cam.lens)}</span>
            </div>
          </RailSection>
          <RailSection title="recording" open={layout.sections.recording} onToggle={() => dispatch({ type: "toggleSection", section: "recording" })}>
            <RecordPanel acquiring={status.state === "acquiring"} />
          </RailSection>
          <RailSection title="display" open={layout.sections.display} onToggle={() => dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode} manual={manual} setManual={setManual} shown={shown} />
          </RailSection>
          {(!layout.strip || !layout.dock) && (
            <div style={{ padding: 10 }}><button className="secondary" onClick={() => dispatch({ type: "restoreAll" })}>restore panels</button></div>
          )}
        </Rail>
      }
    />
  );
}

function fmt(v: number | null | undefined): string { return v == null ? "—" : `${v.toFixed(2)} °C`; }
function fmtAny(v: unknown): string { return v == null ? "—" : typeof v === "number" ? v.toFixed(2) : String(v); }
function kelvin(v: unknown): string { return typeof v === "number" ? `${(v - 273.15).toFixed(1)} °C` : "—"; }
```

- [ ] **Step 2: Trim `DisplayControls.tsx`** — remove its own `<h3>` (the RailSection supplies the title). Replace the component body's opening fragment `<>\n      <h3>Display (visualization only)</h3>` with `<>` and keep everything else.

- [ ] **Step 3: Trim `RecordPanel.tsx`** — remove `<h3>Recording</h3>`; change the Stop button class from inline red style to `className="danger"`; change the state text to render `<span className="badge rec">● REC</span>` when recording.

- [ ] **Step 4: Restyle `SetupPage.tsx`** — wrap the returned `<div className="setup">` as `<div className="page-body">`; keep cards. Replace the `disc` variable's raw string checks with no change (logic unchanged).

- [ ] **Step 5: `ThermalView.tsx`** — the readout uses `white-space: pre` now; change the readout JSX to:

```tsx
<div className="readout">{`x ${hover.x}   y ${hover.y}\nT ${Number.isNaN(hover.t) ? "n/a (not temperature-linear)" : `${hover.t.toFixed(2)} °C`}`}</div>
```

- [ ] **Step 6: Update `PlaybackPage` props signature only** (full rewrite in Task 9). Add to its `Props`: `layout: LayoutState; dispatch: React.Dispatch<LayoutAction>; topbar: React.ReactNode; status: Status; recording: RecordingStatus | null;` with imports `import type { LayoutAction, LayoutState } from "../lib/layout.ts"; import type { RecordingStatus, Status } from "../lib/api.ts";` — unused for now (prefix destructured names with `_` to satisfy `noUnusedLocals`, e.g. `layout: _layout`).

- [ ] **Step 7: Build and check types**

Run: `cd frontend && npm run build`
Expected: `✓ built`, no TS errors.

- [ ] **Step 8: Browser verification** (start `fri-serve` if not running; reload http://localhost:8000)
- Setup page renders in the new chrome: mono wordmark, tabs `live · experiments · setup`, dark deep top bar.
- Connect the camera (or simulated). Live page: tool strip left with `↖` active and the rest greyed, image centered 4:3, dock under the image reading "plots arrive with ROIs (Milestone 6)", rail with four collapsible sections, status bar with mono numbers.
- Status dot: green with glow while frames arrive; disconnect → grey.
- Click the ⛶ strip button: strip, rail and dock disappear, image fills; the rail's "restore panels" is unreachable now, so also verify the `▾` on the dock head and the layout survives a reload (localStorage) then use the browser console `localStorage.removeItem("fri.layout.v1")` and reload to restore.
- Fix: add a restore affordance that is always reachable — a small `⛶` toggle in the top bar right of the tabs: `<button className="secondary" onClick={() => dispatch({ type: layout.strip ? "collapseAll" : "restoreAll" })} title="Toggle panels">⛶</button>` inside `topbar` after `</nav>`.

- [ ] **Step 9: Run all frontend tests and rebuild**, then commit

Run: `npm test && npm run build`
```bash
git add frontend/src
git commit -m "feat(ui): live view in the Studio frame with collapsible strip, rail and dock

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 5: Preview renderer (backend)

**Files:**
- Create: `backend/flir_research_interface/analysis/preview.py`, `backend/tests/test_preview.py`
- Modify: `backend/pyproject.toml` (add `pillow>=10`)

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml` dependencies add `"pillow>=10",`. Run: `cd backend && uv sync --extra dev --inexact` (the `--inexact` keeps PySpin). Expected: `+ pillow==…`.

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_preview.py`

```python
"""Preview/keyframe rendering: visualization-only PNGs derived from the store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from flir_research_interface.analysis.preview import (
    IRON_LUT,
    generate_previews,
    render_keyframes,
    render_preview,
)
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder

W, H = 32, 24


def _exp(root: Path, n: int = 20, finalize: bool = True) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=8)
    d = rec.start(name="pv", metadata={}, camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"})
    for i in range(n):
        counts = np.full((H, W), 29815, dtype=np.uint16)
        counts[H // 2, W // 2] = 29815 + i * 500  # hotspot warming 5 K per frame
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_000_000, host_timestamp_ns=i,
                         pixel_format="Mono16", ir_format="TemperatureLinear10mK", counts=counts, incomplete=False))
    if finalize:
        rec.stop()
    else:
        rec.flush_for_test()
    return d


def _tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted((path / "thermal.zarr").rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_iron_lut_shape_and_endpoints() -> None:
    assert IRON_LUT.shape == (256, 3) and IRON_LUT.dtype == np.uint8
    assert tuple(IRON_LUT[0]) == (0, 0, 0)
    assert IRON_LUT[255].min() > 200  # near white


def test_render_preview_is_rgb_png_of_requested_size() -> None:
    celsius = np.linspace(20, 30, H * W, dtype=np.float32).reshape(H, W)
    png = render_preview(celsius, size=(64, 48))
    img = Image.open(__import__("io").BytesIO(png))
    assert img.size == (64, 48) and img.mode == "RGB"


def test_render_keyframes_strip_geometry() -> None:
    frames = [np.full((H, W), 20.0 + k, dtype=np.float32) for k in range(12)]
    png = render_keyframes(frames, tile=(16, 12), vmin=20.0, vmax=31.0)
    img = Image.open(__import__("io").BytesIO(png))
    assert img.size == (16 * 12, 12)
    # strip gets brighter left -> right (shared scale)
    a = np.asarray(img.convert("L"), dtype=np.float32)
    assert a[:, :16].mean() < a[:, -16:].mean()


def test_generate_previews_writes_files_and_manifest_entries_without_touching_store(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    before = _tree_hash(d)
    out = generate_previews(d)
    assert (d / "preview.png").is_file() and (d / "keyframes.png").is_file()
    assert out["preview"]["frame_index"] == 10 and out["keyframes"]["count"] == 12
    assert out["keyframes"]["indices"][0] == 0 and out["keyframes"]["indices"][-1] == 19
    assert len(out["preview"]["sha256"]) == 64
    assert _tree_hash(d) == before
    man = json.loads((d / "manifest.json").read_text())
    assert man["previews"]["preview"]["file"] == "preview.png"


def test_generate_previews_on_incomplete_experiment(tmp_path: Path) -> None:
    d = _exp(tmp_path, n=5, finalize=False)
    out = generate_previews(d)
    assert (d / "preview.png").is_file()
    assert out["preview"]["frame_index"] == 2
    assert not (d / "manifest.json").exists()  # never fabricate a manifest
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && .venv/bin/pytest tests/test_preview.py -p no:warnings`
Expected: `ModuleNotFoundError: flir_research_interface.analysis.preview`.

- [ ] **Step 4: Implement `backend/flir_research_interface/analysis/preview.py`**

```python
"""Visualization-only preview images for experiments (spec §4).

``preview.png``  : the frame at 50 % of the recording, iron-like palette, auto-scaled to that frame.
``keyframes.png``: 12 frames at 0…100 %, tiled horizontally, one shared scale (whole-run min/max)
                   so the strip shows heating. Used for hover-scrub in the Experiments grid.

These files are derived products. They are written next to the store, listed in the manifest when
one exists, and can be regenerated at any time (``fri-thumbs``). They never modify the store.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.radiometry.temperature_linear import IRFormat, counts_to_celsius

PREVIEW_SIZE = (320, 240)
KEYFRAME_TILE = (160, 120)
KEYFRAME_COUNT = 12

# Same stops as frontend/src/lib/palette.ts (iron-like; not FLIR's LUT).
_IRON_STOPS = [
    (0.00, 0, 0, 0), (0.15, 32, 0, 96), (0.35, 140, 0, 140), (0.55, 220, 60, 40),
    (0.75, 250, 150, 20), (0.90, 255, 220, 60), (1.00, 255, 255, 230),
]


def _build_lut() -> npt.NDArray[np.uint8]:
    xs = np.array([s[0] for s in _IRON_STOPS])
    lut = np.zeros((256, 3), dtype=np.uint8)
    t = np.linspace(0, 1, 256)
    for c in range(3):
        ys = np.array([s[c + 1] for s in _IRON_STOPS], dtype=np.float64)
        lut[:, c] = np.clip(np.rint(np.interp(t, xs, ys)), 0, 255).astype(np.uint8)
    return lut


IRON_LUT: npt.NDArray[np.uint8] = _build_lut()


def _colorize(celsius: npt.NDArray[np.float32], vmin: float, vmax: float) -> npt.NDArray[np.uint8]:
    span = vmax - vmin
    idx = np.zeros(celsius.shape, dtype=np.uint8) if span <= 0 else np.clip(
        np.rint((celsius - vmin) * (255.0 / span)), 0, 255
    ).astype(np.uint8)
    return IRON_LUT[idx]


def _png(rgb: npt.NDArray[np.uint8], size: tuple[int, int] | None) -> bytes:
    img = Image.fromarray(rgb, mode="RGB")
    if size is not None and img.size != size:
        img = img.resize(size, Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_preview(celsius: npt.NDArray[np.float32], *, size: tuple[int, int] = PREVIEW_SIZE) -> bytes:
    """PNG of one frame, auto-scaled to its own finite min/max."""
    finite = celsius[np.isfinite(celsius)]
    vmin, vmax = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    return _png(_colorize(np.nan_to_num(celsius, nan=vmin), vmin, vmax), size)


def render_keyframes(
    frames: list[npt.NDArray[np.float32]], *, tile: tuple[int, int] = KEYFRAME_TILE, vmin: float, vmax: float
) -> bytes:
    """Horizontal strip of frames on a shared scale."""
    tiles = []
    for f in frames:
        rgb = _colorize(np.nan_to_num(f, nan=vmin), vmin, vmax)
        tiles.append(np.asarray(Image.fromarray(rgb, mode="RGB").resize(tile, Image.Resampling.NEAREST)))
    strip = np.concatenate(tiles, axis=1)
    return _png(strip, None)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate_previews(exp_dir: Path) -> dict[str, Any]:
    """Render preview.png + keyframes.png for an experiment; update manifest.previews if a manifest exists."""
    r = ExperimentReader(exp_dir)
    n = r.n_frames
    if n == 0:
        raise ValueError("experiment has no frames")
    fmt = IRFormat(r.ir_format) if r.ir_format else None

    def celsius(i: int) -> npt.NDArray[np.float32]:
        counts = r.frame(i).counts
        if fmt is None or fmt == IRFormat.RADIOMETRIC:
            return counts.astype(np.float32)  # raw counts; still a valid picture
        return counts_to_celsius(counts, fmt)

    mid = n // 2
    preview_png = render_preview(celsius(mid))
    indices = sorted({int(round(k * (n - 1) / (KEYFRAME_COUNT - 1))) for k in range(KEYFRAME_COUNT)})
    while len(indices) < KEYFRAME_COUNT:  # short runs: repeat last index
        indices.append(indices[-1])
    frames = [celsius(i) for i in indices]
    vmin = float(min(np.nanmin(f) for f in frames))
    vmax = float(max(np.nanmax(f) for f in frames))
    keyframes_png = render_keyframes(frames, vmin=vmin, vmax=vmax)

    (exp_dir / "preview.png").write_bytes(preview_png)
    (exp_dir / "keyframes.png").write_bytes(keyframes_png)
    out: dict[str, Any] = {
        "preview": {"file": "preview.png", "frame_index": mid, "t_s": r.t_s(mid),
                    "size": list(PREVIEW_SIZE), "sha256": _sha256(preview_png)},
        "keyframes": {"file": "keyframes.png", "count": KEYFRAME_COUNT, "indices": indices,
                      "t_s": [r.t_s(i) for i in indices], "tile": list(KEYFRAME_TILE),
                      "vmin_c": vmin, "vmax_c": vmax, "sha256": _sha256(keyframes_png)},
    }
    man_path = exp_dir / "manifest.json"
    if man_path.is_file():
        man = json.loads(man_path.read_text())
        man["previews"] = out
        man_path.write_text(json.dumps(man, indent=2))
    return out


__all__ = ["IRON_LUT", "KEYFRAME_COUNT", "generate_previews", "render_keyframes", "render_preview"]
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_preview.py -p no:warnings`
Expected: 5 passed.

- [ ] **Step 6: Lint/type, commit**

Run: `.venv/bin/ruff format flir_research_interface tests && .venv/bin/ruff check . && .venv/bin/mypy flir_research_interface`
```bash
git add backend/pyproject.toml backend/uv.lock backend/flir_research_interface/analysis/preview.py backend/tests/test_preview.py
git commit -m "feat(preview): iron preview.png and 12-keyframe strip rendered from the store

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 6: Previews at finalize, on-demand regeneration, preview endpoints

**Files:**
- Modify: `backend/flir_research_interface/recording/recorder.py` (`_write_manifest`), `backend/flir_research_interface/playback/reader.py` (`info()`), `backend/flir_research_interface/api/app.py`, `backend/pyproject.toml` (`fri-thumbs`)
- Create: `backend/flir_research_interface/thumbs.py`, `backend/tests/test_api_previews.py`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_api_previews.py`

```python
"""Preview endpoints and finalize-time preview generation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.camera.base import Frame
from flir_research_interface.recording.recorder import Recorder


def _exp(root: Path, n: int = 6) -> Path:
    rec = Recorder(None, experiments_root=root, chunk_frames=4)
    d = rec.start(name="pv", metadata={}, camera_info={"backend": "simulated", "ir_format": "TemperatureLinear10mK"})
    for i in range(n):
        rec.submit(Frame(frame_id=i, device_timestamp_ns=i * 33_000_000, host_timestamp_ns=i, pixel_format="Mono16",
                         ir_format="TemperatureLinear10mK", counts=np.full((8, 10), 30000 + i, np.uint16), incomplete=False))
    rec.stop()
    return d


def test_finalize_writes_previews_and_manifest_lists_them(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    assert (d / "preview.png").is_file() and (d / "keyframes.png").is_file()
    man = json.loads((d / "manifest.json").read_text())
    assert man["previews"]["preview"]["file"] == "preview.png"
    assert man["complete"] is True


def test_preview_endpoints_serve_png_and_listing_exposes_previews(tmp_path: Path) -> None:
    d = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        r = c.get(f"/api/experiments/{d.name}/preview.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
        r = c.get(f"/api/experiments/{d.name}/keyframes.png")
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
        items = c.get("/api/experiments").json()
        assert items[0]["previews"]["keyframes"]["count"] == 12
        # regenerate on demand
        (d / "preview.png").unlink()
        r = c.post(f"/api/experiments/{d.name}/previews")
        assert r.status_code == 200 and (d / "preview.png").is_file()
        assert c.get("/api/experiments/nope/preview.png").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_api_previews.py -p no:warnings`
Expected: first test fails (`preview.png` missing), second fails with 404s.

- [ ] **Step 3: Recorder: render previews at finalize** — in `recorder.py`, `_write_manifest`, after `(self._exp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))` add:

```python
        try:
            from flir_research_interface.analysis.preview import generate_previews

            manifest["previews"] = generate_previews(self._exp_dir)  # also rewrites manifest.json
        except Exception as exc:  # noqa: BLE001 - previews must never fail finalization
            logger.warning("preview generation failed: %s", exc)
            manifest["previews"] = None
```

(The import is local to avoid a recorder→playback→recorder import cycle at module load.)

- [ ] **Step 4: Reader: expose previews** — in `reader.py` `info()` add `"previews": (self.manifest or {}).get("previews"),`.

- [ ] **Step 5: API endpoints** — in `app.py` after `experiment_frame`:

```python
    def _png_response(path: Path) -> Response:
        if not path.is_file():
            raise HTTPException(404, f"{path.name} not generated yet")
        return Response(content=path.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/experiments/{name}/preview.png")
    def experiment_preview(name: str) -> Response:
        return _png_response(_open(name).path / "preview.png")

    @app.get("/api/experiments/{name}/keyframes.png")
    def experiment_keyframes(name: str) -> Response:
        return _png_response(_open(name).path / "keyframes.png")

    @app.post("/api/experiments/{name}/previews")
    async def experiment_regenerate_previews(name: str) -> dict[str, Any]:
        from flir_research_interface.analysis.preview import generate_previews

        r = _open(name)
        try:
            return await run_in_threadpool(generate_previews, r.path)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
```

- [ ] **Step 6: `fri-thumbs` CLI** — create `backend/flir_research_interface/thumbs.py`

```python
"""``fri-thumbs``: (re)generate preview.png / keyframes.png for recorded experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

from flir_research_interface.analysis.preview import generate_previews


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate experiment previews")
    p.add_argument("root", nargs="?", default="experiments", help="experiments root or one experiment dir")
    p.add_argument("--force", action="store_true", help="regenerate even if preview.png exists")
    args = p.parse_args(argv)
    root = Path(args.root)
    dirs = [root] if (root / "metadata.json").is_file() else sorted(d for d in root.iterdir() if d.is_dir())
    rc = 0
    for d in dirs:
        if not args.force and (d / "preview.png").is_file() and (d / "keyframes.png").is_file():
            print(f"{d.name}: up to date")
            continue
        try:
            out = generate_previews(d)
            print(f"{d.name}: preview frame {out['preview']['frame_index']}, {out['keyframes']['count']} keyframes")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{d.name}: FAILED {type(exc).__name__}: {exc}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
```

Add to `pyproject.toml` `[project.scripts]`: `fri-thumbs = "flir_research_interface.thumbs:main"`, then `uv sync --extra dev --inexact`.

- [ ] **Step 7: Run tests, gate, generate previews for the existing run**

Run: `.venv/bin/pytest -p no:warnings` → all pass. `.venv/bin/ruff check . && .venv/bin/mypy flir_research_interface`.
Run: `.venv/bin/fri-thumbs experiments` → prints one line per experiment; `ls experiments/*/preview.png`.

- [ ] **Step 8: Commit**

```bash
git add backend
git commit -m "feat(preview): previews at finalize, preview/keyframe endpoints, fri-thumbs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 7: Reveal in file manager (backend)

**Files:**
- Create: `backend/flir_research_interface/api/reveal.py`, `backend/tests/test_reveal.py`
- Modify: `backend/flir_research_interface/api/app.py`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_reveal.py`

```python
"""Reveal-in-file-manager: command selection, path containment, endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from flir_research_interface.api.reveal import contained, reveal, reveal_command


def test_reveal_command_per_os(tmp_path: Path) -> None:
    p = tmp_path / "exp"
    assert reveal_command("Darwin", p) == ["open", "-R", str(p)]
    assert reveal_command("Windows", p) == ["explorer", f"/select,{p}"]
    assert reveal_command("Linux", p) == ["xdg-open", str(p.parent)]
    with pytest.raises(ValueError):
        reveal_command("Plan9", p)


def test_contained_rejects_escapes_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    root.mkdir()
    (root / "a").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    assert contained(root, root / "a") is True
    assert contained(root, root / ".." / "outside") is False
    assert contained(root, root / "link") is False


def test_reveal_uses_injected_runner_and_reports(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    res = reveal(tmp_path, system="Darwin", runner=lambda cmd: calls.append(cmd) or 0)
    assert calls == [["open", "-R", str(tmp_path)]] and res["ok"] is True
    res2 = reveal(tmp_path, system="Linux", runner=lambda _c: 127)
    assert res2["ok"] is False and "xdg-open" in res2["error"]


def test_reveal_endpoints(tmp_path: Path) -> None:
    (tmp_path / "20260901_x").mkdir()
    (tmp_path / "20260901_x" / "metadata.json").write_text("{}")
    app = create_app(experiments_root=tmp_path, reveal_runner=lambda _c: 0)
    with TestClient(app) as c:
        r = c.post("/api/experiments/20260901_x/reveal")
        assert r.status_code == 200 and r.json()["ok"] is True and r.json()["path"].endswith("20260901_x")
        assert c.post("/api/experiments/../etc/reveal").status_code in (400, 404)
        assert c.post("/api/experiments/missing/reveal").status_code == 404
        r = c.post("/api/experiments/reveal-root")
        assert r.status_code == 200 and r.json()["ok"] is True
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_reveal.py -p no:warnings` → `ModuleNotFoundError: ...api.reveal`.

- [ ] **Step 3: Implement `backend/flir_research_interface/api/reveal.py`**

```python
"""Open an experiment folder in the OS file manager (spec §5). Local-operator feature."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[[list[str]], int]


def reveal_command(system: str, path: Path) -> list[str]:
    if system == "Darwin":
        return ["open", "-R", str(path)]
    if system == "Windows":
        return ["explorer", f"/select,{path}"]
    if system == "Linux":
        return ["xdg-open", str(path.parent)]
    raise ValueError(f"no file manager integration for {system!r}")


def contained(root: Path, path: Path) -> bool:
    """True if ``path`` resolves inside ``root`` (symlinks resolved, no escape)."""
    try:
        root_r = root.resolve(strict=True)
        path_r = path.resolve(strict=True)
    except OSError:
        return False
    if path.is_symlink():
        return False
    return path_r == root_r or root_r in path_r.parents


def _default_runner(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, check=False, timeout=10).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


def reveal(path: Path, *, system: str | None = None, runner: Runner = _default_runner) -> dict[str, Any]:
    system = system or platform.system()
    try:
        cmd = reveal_command(system, path)
    except ValueError as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}
    rc = runner(cmd)
    if rc != 0:
        return {"ok": False, "path": str(path), "error": f"{cmd[0]} exited with {rc}"}
    return {"ok": True, "path": str(path), "command": cmd}


__all__ = ["Runner", "contained", "reveal", "reveal_command"]
```

- [ ] **Step 4: Wire endpoints** — in `app.py`:
  - `create_app(...)` gets a new keyword `reveal_runner: Runner | None = None` (import `from flir_research_interface.api.reveal import Runner, contained, reveal`), stored as `app.state.reveal_runner`.
  - Add after the preview endpoints:

```python
    def _reveal(path: Path) -> dict[str, Any]:
        root: Path = app.state.experiments_root
        if not contained(root, path):
            raise HTTPException(400, "path is outside the experiments root")
        kwargs: dict[str, Any] = {}
        if app.state.reveal_runner is not None:
            kwargs["runner"] = app.state.reveal_runner
        res = reveal(path, **kwargs)
        if not res["ok"] and "no file manager" in res.get("error", ""):
            raise HTTPException(501, res["error"])
        return res

    @app.post("/api/experiments/reveal-root")
    def reveal_root() -> dict[str, Any]:
        root: Path = app.state.experiments_root
        root.mkdir(parents=True, exist_ok=True)
        return _reveal(root)

    @app.post("/api/experiments/{name}/reveal")
    def reveal_experiment(name: str) -> dict[str, Any]:
        root: Path = app.state.experiments_root
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            raise HTTPException(400, "invalid experiment name")
        d = root / name
        if not d.is_dir():
            raise HTTPException(404, f"experiment {name!r} not found")
        return _reveal(d)
```

  Route order matters: define `/api/experiments/reveal-root` **before** `/api/experiments/{name}` GET/POST routes that could shadow it (FastAPI matches in declaration order; a POST to `reveal-root` cannot match the GET `{name}` route, but keep it first anyway for clarity).

- [ ] **Step 5: Run tests and gate** — `.venv/bin/pytest -p no:warnings && .venv/bin/ruff check . && .venv/bin/mypy flir_research_interface` → all green.

- [ ] **Step 6: Manual check on this Mac** — with the server running: `curl -X POST http://127.0.0.1:8000/api/experiments/reveal-root` → Finder opens the experiments folder.

- [ ] **Step 7: Commit**

```bash
git add backend/flir_research_interface/api/reveal.py backend/flir_research_interface/api/app.py backend/tests/test_reveal.py
git commit -m "feat(api): reveal experiment folder in Finder/Explorer/xdg with path containment

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 8: Experiments card grid with hover-scrub

**Files:**
- Create: `frontend/src/lib/keyframes.ts`, `frontend/src/lib/keyframes.test.ts`, `frontend/src/components/ExperimentCard.tsx`
- Modify: `frontend/src/components/ExperimentsPage.tsx` (replace), `frontend/src/lib/api.ts`

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/keyframes.test.ts`

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { keyframeIndex, keyframeBackgroundPosition, formatSeconds } from "./keyframes.ts";

test("keyframeIndex maps mouse x across the width to 0..count-1", () => {
  assert.equal(keyframeIndex(0, 300, 12), 0);
  assert.equal(keyframeIndex(299, 300, 12), 11);
  assert.equal(keyframeIndex(150, 300, 12), 6);
  assert.equal(keyframeIndex(-5, 300, 12), 0);
  assert.equal(keyframeIndex(1000, 300, 12), 11);
  assert.equal(keyframeIndex(10, 0, 12), 0);
});

test("keyframeBackgroundPosition selects tile k of a horizontal strip", () => {
  assert.equal(keyframeBackgroundPosition(0, 12), "0% 0");
  assert.equal(keyframeBackgroundPosition(11, 12), "100% 0");
  assert.match(keyframeBackgroundPosition(6, 12), /^54\.5\d+% 0$/);
});

test("formatSeconds", () => {
  assert.equal(formatSeconds(3.8961), "3.90 s");
  assert.equal(formatSeconds(75.2), "1:15.2");
});
```

- [ ] **Step 2: Run to verify failure** — `npm test` → cannot find `./keyframes.ts`.

- [ ] **Step 3: Implement `frontend/src/lib/keyframes.ts`**

```ts
/** Hover-scrub helpers for the Experiments grid (spec §4). */

export function keyframeIndex(x: number, width: number, count: number): number {
  if (width <= 0 || count <= 1) return 0;
  const i = Math.floor((x / width) * count);
  return Math.min(Math.max(i, 0), count - 1);
}

/** CSS background-position for tile k of a horizontal strip with background-size count*100%. */
export function keyframeBackgroundPosition(k: number, count: number): string {
  if (count <= 1) return "0% 0";
  return `${(k / (count - 1)) * 100}% 0`;
}

export function formatSeconds(t: number): string {
  if (t < 60) return `${t.toFixed(2)} s`;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
```

- [ ] **Step 4: Run tests** — `npm test` → pass.

- [ ] **Step 5: API helpers** — in `frontend/src/lib/api.ts` add inside `api`:

```ts
  previewUrl: (name: string) => `/api/experiments/${encodeURIComponent(name)}/preview.png`,
  keyframesUrl: (name: string) => `/api/experiments/${encodeURIComponent(name)}/keyframes.png`,
  regeneratePreviews: (name: string) => j<Record<string, unknown>>(fetch(`/api/experiments/${encodeURIComponent(name)}/previews`, { method: "POST" })),
  reveal: (name: string) => j<{ ok: boolean; path: string; error?: string }>(fetch(`/api/experiments/${encodeURIComponent(name)}/reveal`, { method: "POST" })),
  revealRoot: () => j<{ ok: boolean; path: string; error?: string }>(fetch("/api/experiments/reveal-root", { method: "POST" })),
```

and extend `Experiment` with `previews?: { preview: { frame_index: number; t_s: number }; keyframes: { count: number; t_s: number[]; vmax_c: number } } | null; ir_format?: string | null; duration_s?: number; n_frames?: number; experiment?: Record<string, unknown> | null;`.

- [ ] **Step 6: Create `frontend/src/components/ExperimentCard.tsx`**

```tsx
import { useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { formatSeconds, keyframeBackgroundPosition, keyframeIndex } from "../lib/keyframes.ts";

interface Props { exp: Experiment; onOpen: () => void; }

export function ExperimentCard({ exp, onOpen }: Props) {
  const [k, setK] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const kf = exp.previews?.keyframes;
  const count = kf?.count ?? 0;
  const n = exp.n_frames ?? exp.frames_on_disk;
  const meta = exp.experiment ?? {};
  const cacheKey = exp.manifest ? String((exp.manifest as { finished_utc?: string }).finished_utc ?? "") : String(n);

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!count) return;
    const r = e.currentTarget.getBoundingClientRect();
    setK(keyframeIndex(e.clientX - r.left, r.width, count));
  }
  async function reveal() {
    setBusy(true); setNote(null);
    try { const r = await api.reveal(exp.name); setNote(r.ok ? null : `${r.error} — ${r.path}`); }
    catch (err) { setNote(String(err)); } finally { setBusy(false); }
  }
  async function regen() {
    setBusy(true); setNote(null);
    try { await api.regeneratePreviews(exp.name); location.reload(); } catch (err) { setNote(String(err)); } finally { setBusy(false); }
  }

  return (
    <div className="exp-card">
      <div className="thumb" onMouseMove={onMove} onMouseLeave={() => setK(null)} onClick={onOpen} title="open">
        {exp.previews ? (
          <>
            <img src={`${api.previewUrl(exp.name)}?v=${encodeURIComponent(cacheKey)}`} alt="" />
            {k !== null && kf && (
              <div className="kf" style={{ backgroundImage: `url(${api.keyframesUrl(exp.name)}?v=${encodeURIComponent(cacheKey)})`,
                backgroundPosition: keyframeBackgroundPosition(k, count) }} />
            )}
            <span className="t">{k !== null && kf ? `t = ${formatSeconds(kf.t_s[k] ?? 0)}` : `${n} frames · ${exp.duration_s != null ? formatSeconds(exp.duration_s) : "—"}`}</span>
          </>
        ) : (
          <div className="ph">no preview{n ? <button className="secondary" style={{ marginLeft: 8 }} disabled={busy} onClick={(e) => { e.stopPropagation(); void regen(); }}>generate</button> : null}</div>
        )}
      </div>
      <div className="body">
        <span className="name">{exp.name}</span>
        <span className="meta">
          {exp.duration_s != null && <span>{formatSeconds(exp.duration_s)}</span>}
          <span>{n} fr</span>
          {exp.ir_format && <span>{exp.ir_format.replace("TemperatureLinear", "TL ")}</span>}
          {meta.material != null && <span>{String(meta.material)}</span>}
          {meta.rf_forward_power_w != null && <span>{String(meta.rf_forward_power_w)} W</span>}
        </span>
        <span>{exp.complete ? <span className="badge ok">complete</span> : <span className="badge bad">INCOMPLETE{exp.manifest && (exp.manifest as { queue_dropped?: number }).queue_dropped ? ` · ${(exp.manifest as { queue_dropped?: number }).queue_dropped} dropped` : ""}</span>}</span>
        <div className="actions">
          <button className="primary" disabled={!n} onClick={onOpen}>open</button>
          <button className="secondary" disabled={busy} onClick={reveal} title="Show in Finder / Explorer">reveal</button>
          <button className="secondary" disabled title="Milestone 7">export</button>
        </div>
        {note && <div className="errbox">{note}</div>}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Replace `frontend/src/components/ExperimentsPage.tsx`**

```tsx
import { useEffect, useMemo, useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { ExperimentCard } from "./ExperimentCard.tsx";

type Sort = "newest" | "name" | "duration";

export function ExperimentsPage({ onOpen }: { onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Experiment[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("newest");
  const [q, setQ] = useState("");
  useEffect(() => { api.experiments().then(setItems).catch((e) => setErr(String(e))); }, []);

  const shown = useMemo(() => {
    if (!items) return [];
    const f = q.trim().toLowerCase();
    const list = items.filter((e) => !f || e.name.toLowerCase().includes(f) || JSON.stringify(e.experiment ?? {}).toLowerCase().includes(f));
    return list.sort((a, b) => sort === "name" ? a.name.localeCompare(b.name)
      : sort === "duration" ? (b.duration_s ?? 0) - (a.duration_s ?? 0) : b.name.localeCompare(a.name));
  }, [items, sort, q]);

  return (
    <div className="page-body">
      <div className="exp-head">
        <span>{items ? `${items.length} experiments` : "loading…"}</span>
        <span className="right">
          <input type="text" placeholder="filter" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 160 }} />
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="newest">newest</option><option value="name">name</option><option value="duration">duration</option>
          </select>
          <button className="secondary" onClick={() => void api.revealRoot()}>open folder</button>
        </span>
      </div>
      {err && <div className="errbox">{err}</div>}
      {items && items.length === 0 && <div className="muted">No experiments yet. Record one from the live view.</div>}
      <div className="exp-grid">
        {shown.map((e) => <ExperimentCard key={e.name} exp={e} onOpen={() => onOpen(e.name)} />)}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Build, run tests, browser check** — `npm test && npm run build`; reload; Experiments tab shows the card with the iron preview; moving the mouse across the thumbnail scrubs through 12 keyframes and updates `t = … s`; "reveal" opens Finder; "open folder" opens the experiments root.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): experiments card grid with mid-capture preview, hover-scrub keyframes, reveal

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 9: Playback inside the Studio frame

**Files:**
- Modify: `frontend/src/components/PlaybackPage.tsx` (replace)

- [ ] **Step 1: Replace `PlaybackPage.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ExperimentInfo, type RecordingStatus, type Status, type Timeline } from "../lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "../lib/protocol.ts";
import type { PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import type { LayoutAction, LayoutState } from "../lib/layout.ts";
import { SPEEDS, clampIndex, nextFrameDelayMs, speedLabel } from "../lib/playback.ts";
import { ThermalView } from "./ThermalView.tsx";
import { DisplayControls } from "./DisplayControls.tsx";
import { StudioFrame } from "./studio/StudioFrame.tsx";
import { Rail } from "./studio/Rail.tsx";
import { RailSection } from "./studio/RailSection.tsx";
import { PlotDock } from "./studio/PlotDock.tsx";
import { StatusBar } from "./studio/StatusBar.tsx";

interface Props {
  name: string;
  layout: LayoutState; dispatch: React.Dispatch<LayoutAction>; topbar: React.ReactNode;
  status: Status; recording: RecordingStatus | null;
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  onBack: () => void;
}

export function PlaybackPage(p: Props) {
  const [info, setInfo] = useState<ExperimentInfo | null>(null);
  const [tl, setTl] = useState<Timeline | null>(null);
  const [index, setIndex] = useState(0);
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [shown, setShown] = useState<Range>({ min: 0, max: 100 });
  const [err, setErr] = useState<string | null>(null);
  const cache = useRef(new Map<number, FrameMessage>());
  const n = info?.n_frames ?? 0;

  useEffect(() => {
    cache.current.clear();
    Promise.all([api.experiment(p.name), api.timeline(p.name)])
      .then(([i, t]) => { setInfo(i); setTl(t); setIndex(0); }).catch((e) => setErr(String(e)));
  }, [p.name]);

  const load = useCallback(async (i: number): Promise<FrameMessage> => {
    const hit = cache.current.get(i);
    if (hit) return hit;
    const msg = decodeFrameMessage(await api.frameBuffer(p.name, i));
    if (cache.current.size > 64) cache.current.delete(cache.current.keys().next().value as number);
    cache.current.set(i, msg);
    return msg;
  }, [p.name]);

  useEffect(() => {
    if (!info || n === 0) return;
    let alive = true;
    load(index).then((m) => { if (alive) setFrame(m); }).catch((e) => setErr(String(e)));
    if (index + 1 < n) void load(index + 1).catch(() => undefined);
    return () => { alive = false; };
  }, [index, info, n, load]);

  useEffect(() => {
    if (!playing || !tl || n === 0) return;
    if (index >= n - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setIndex((i) => clampIndex(i + 1, n)), nextFrameDelayMs(tl.t_s[index], tl.t_s[index + 1], speed));
    return () => window.clearTimeout(t);
  }, [playing, index, tl, n, speed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === " ") { e.preventDefault(); setPlaying((v) => !v); }
      if (e.key === "ArrowRight") setIndex((i) => clampIndex(i + 1, n));
      if (e.key === "ArrowLeft") setIndex((i) => clampIndex(i - 1, n));
      if (e.key === "Home") setIndex(0);
      if (e.key === "End") setIndex(clampIndex(n - 1, n));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n]);

  const t = tl ? tl.t_s[index] : 0;
  const hdr = frame?.header;
  const exp = (info?.experiment ?? {}) as Record<string, unknown>;
  const cam = (info?.camera ?? {}) as Record<string, unknown>;
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;

  const transport = (
    <span style={{ display: "flex", gap: 8, alignItems: "center", flex: 1 }}>
      <button className="secondary" onClick={() => setIndex(0)} title="Home">⏮</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i - 1, n))} title="←">◀︎</button>
      <button className="primary" style={{ minWidth: 64 }} onClick={() => setPlaying((v) => !v)}>{playing ? "pause" : "play"}</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i + 1, n))} title="→">▶︎</button>
      <button className="secondary" onClick={() => setIndex(clampIndex(n - 1, n))} title="End">⏭</button>
      <select value={String(speed)} onChange={(e) => setSpeed(Number(e.target.value))}>
        {SPEEDS.map((s) => <option key={String(s)} value={String(s)}>{speedLabel(s)}</option>)}
      </select>
      <input type="range" min={0} max={Math.max(n - 1, 0)} value={index} style={{ flex: 1, minWidth: 120 }}
        onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }} />
      <b style={{ minWidth: 150, textAlign: "right" }}>{t.toFixed(3)} s · {index + 1}/{n}</b>
    </span>
  );

  return (
    <StudioFrame layout={p.layout} topbar={p.topbar}
      strip={<nav className="strip"><button className="active" title="Back to experiments" onClick={p.onBack}>←</button></nav>}
      center={<ThermalView frame={frame} palette={p.palette} scaleMode={p.scaleMode} manual={p.manual} onScale={setShown} />}
      dock={<PlotDock title="temperature vs time (whole recording)" onCollapse={() => p.dispatch({ type: "toggle", panel: "dock" })} />}
      rail={
        <Rail>
          <RailSection title="experiment" open={p.layout.sections.experiment} onToggle={() => p.dispatch({ type: "toggleSection", section: "experiment" })}>
            <div className="kv">
              <span>name</span><span className="v plain" style={{ fontSize: 11 }}>{p.name}</span>
              <span>frames</span><span className="v plain">{n}</span>
              <span>duration</span><span className="v plain">{info ? `${info.duration_s.toFixed(2)} s` : "—"}</span>
              <span>status</span><span className="v plain">{info ? (info.complete ? "complete" : "INCOMPLETE") : "—"}</span>
              <span>format</span><span className="v plain">{info?.ir_format ?? "—"}</span>
              <span>case</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              {Object.entries(exp).filter(([k]) => k !== "name").map(([k, v]) => (<><span key={`k${k}`}>{k}</span><span key={`v${k}`} className="v plain">{String(v)}</span></>))}
            </div>
          </RailSection>
          <RailSection title="measurements" open={p.layout.sections.measurements} onToggle={() => p.dispatch({ type: "toggleSection", section: "measurements" })} tag="this frame">
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmt(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmt(hdr.min_c)}</span>
                <span>max</span><span className="v">{fmt(hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmt(hdr.mean_c)}</span>
                <span>frame id</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">loading…</div>}
            {err && <div className="errbox">{err}</div>}
          </RailSection>
          <RailSection title="display" open={p.layout.sections.display} onToggle={() => p.dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={p.palette} setPalette={p.setPalette} scaleMode={p.scaleMode} setScaleMode={p.setScaleMode} manual={p.manual} setManual={p.setManual} shown={shown} />
          </RailSection>
        </Rail>
      }
      statusbar={<StatusBar status={p.status} recording={p.recording} displayFps={0} stale={false} left={transport} />}
    />
  );
}

function fmt(v: number | null | undefined): string { return v == null ? "—" : `${v.toFixed(2)} °C`; }
```

- [ ] **Step 2: In `App.tsx`**, the playback branch already passes `layout, dispatch, topbar, status, recording` (Task 4 Step 1). Remove any `_`-prefixed unused destructuring left from Task 4 Step 6.

- [ ] **Step 3: Build and browser check** — `npm run build`; reload; Experiments → open → playback shows in the Studio frame: `←` in the strip returns to the grid, transport in the status bar, dock placeholder, rail sections. Play advances; scrub works; keyboard works.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): playback in the Studio frame with transport in the status bar

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Task 10: Docs, README, plan file

**Files:**
- Modify: `README.md` (status table rows for UI system, previews, reveal), `docs/architecture.md` (§ "Frontend" paragraph: tokens, Studio frame, previews as derived products, reveal), `docs/data_format.md` (add `preview.png`, `keyframes.png`, `manifest.previews` to the layout block), `plan/task_plan.md` (mark UI plan done; note deployment plan next).

- [ ] **Step 1: Apply the edits**

`docs/data_format.md`, in the layout block, add after `events.json`:
```
    preview.png          VISUALIZATION ONLY: frame at 50 %, iron palette, 320x240 (regenerable)
    keyframes.png        VISUALIZATION ONLY: 12 frames 0..100 % tiled horizontally, shared scale
```
and a sentence under "An experiment directory without manifest.json…": "Preview images are derived
products listed under `manifest.previews` (with sha256); deleting them loses nothing — `fri-thumbs`
regenerates them from the store."

`docs/architecture.md`, append a section:
```
## 6c. Frontend system (UI spec 2026-09-01)

Tokens live in `frontend/src/theme.css` (fonts self-hosted); the Studio frame
(`components/studio/`) provides tool strip, center image + plot dock, right rail with
collapsible sections, and a status bar that never shows green. Layout state persists in
`localStorage` (`fri.layout.v1`). Experiments render as cards with `preview.png` and a 12-frame
`keyframes.png` for hover-scrub; both are derived from the store by `analysis/preview.py` at
finalize (or `fri-thumbs`). "Reveal" calls `/api/experiments/{name}/reveal`, which opens the folder
with the OS file manager after verifying the path is inside the experiments root.
```

`README.md`: add rows `| UI system + Studio layout | frontend/src/theme.css, components/studio/ | verified in browser |`, `| Experiment previews + hover-scrub + reveal | analysis/preview.py, api/reveal.py, ExperimentCard.tsx | tested |`.

- [ ] **Step 2: Full gate**

Run: `cd backend && .venv/bin/pytest -p no:warnings && .venv/bin/ruff check . && .venv/bin/mypy flir_research_interface && cd ../frontend && npm test && npm run build`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add README.md docs plan
git commit -m "docs: UI system, previews and reveal in architecture/data-format/README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- §2 visual system → Task 1 (tokens, fonts), Task 3 (styles, dot semantics, buttons), Task 4 (wordmark, tabs, rail typography). Light theme explicitly out of scope. ✔
- §3 Studio layout → Tasks 3–4 (strip with disabled future tools, image, dock placeholder, rail sections incl. "read-only until M6" camera section, status bar without green, collapse + persistence via Task 2). Camera *controls* themselves are plan 3 (spec sequencing item 6). ✔
- §4 Experiments → Tasks 5, 6, 8 (preview at 50 %, 12 keyframes shared scale, hover-scrub, actions, incomplete handling, regenerate, `fri-thumbs`). ✔
- §5 Reveal → Task 7 (+ UI buttons in Task 8), 501 path, containment. ✔
- §6 Deployment → **separate plan** (next). §7 data flow: preview/keyframe/reveal endpoints ✔; `api_version`, SDK install job, `X-FRI-Client` → deployment plan. ✔
- §8 error handling → preview failure never fails finalization (Task 6 Step 3), reveal 501 + path shown (Tasks 7–8), placeholder + regenerate (Task 8). ✔
- §9 testing → node tests for theme/layout/keyframes; pytest for preview, reveal, endpoints; browser checks listed per UI task. ✔
- Type consistency: `LayoutState`/`LayoutAction`/`Tool`/`Section` names match across Tasks 2, 3, 4, 9; `Experiment.previews` shape in Task 8 matches `generate_previews` output in Task 5; `RecordingStatus`/`Status` imports match `api.ts`. ✔
