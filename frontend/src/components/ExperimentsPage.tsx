import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { storageBreakdown, summaryLabel } from "../lib/storageSummary.ts";
import {
  filterExperiments, mergeTags, selectionReducer, sortExperiments, tagUniverse,
  type Sort, type SelectionState,
} from "../lib/organize.ts";
import { ExperimentCard } from "./ExperimentCard.tsx";
import { SelectionBar } from "./SelectionBar.tsx";
import { TagPopover } from "./TagPopover.tsx";

const cardId = (e: { library?: string; name: string }) => `${e.library ?? "local"}:${e.name}`;
const ls = {
  get: (k: string, d: string) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

export function ExperimentsPage({ onOpen }: { onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Experiment[] | null>(null);
  const [driveConnected, setDriveConnected] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>(() => ls.get("fri.sort", "newest") as Sort);
  const [q, setQ] = useState("");
  const [starredOnly, setStarredOnly] = useState(() => ls.get("fri.starredOnly", "0") === "1");
  const [tagFilter, setTagFilter] = useState<string[]>(() => {
    try { return JSON.parse(ls.get("fri.tagFilter", "[]")); } catch { return []; }
  });
  const [fullVerify, setFullVerify] = useState(() => ls.get("fri.fullVerify", "0") === "1");
  const [selecting, setSelecting] = useState(false);
  const [sel, dispatch] = useReducer(selectionReducer, { anchor: null, selected: new Set() } as SelectionState);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<string | null>(null);
  const [bulkTagOpen, setBulkTagOpen] = useState(false);

  const setSortP = (s: Sort) => { setSort(s); ls.set("fri.sort", s); };
  const setStarredP = (on: boolean) => { setStarredOnly(on); ls.set("fri.starredOnly", on ? "1" : "0"); };
  const setTagsP = (t: string[]) => { setTagFilter(t); ls.set("fri.tagFilter", JSON.stringify(t)); };
  const toggleFullVerify = (on: boolean) => { setFullVerify(on); ls.set("fri.fullVerify", on ? "1" : "0"); };
  const addTagFilter = (t: string) => { if (!tagFilter.includes(t)) setTagsP([...tagFilter, t]); };

  const load = useCallback(() => {
    api.experiments().then(setItems).catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => {
    let alive = true;
    const tick = () => {
      api.storage().then((s) => { if (alive) setDriveConnected(!!s.drive?.connected); }).catch(() => undefined);
      load();
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [load]);

  const breakdown = useMemo(() => storageBreakdown(items ?? []), [items]);
  const universe = useMemo(() => tagUniverse(items ?? []).map((t) => t.tag), [items]);
  const shown = useMemo(
    () => sortExperiments(filterExperiments(items ?? [], { query: q, starredOnly, tags: tagFilter }), sort),
    [items, q, starredOnly, tagFilter, sort],
  );
  const shownIds = useMemo(() => shown.map(cardId), [shown]);
  const byId = useMemo(() => new Map(shown.map((e) => [cardId(e), e])), [shown]);
  const filtering = q.trim().length > 0 || starredOnly || tagFilter.length > 0;

  const selectedItems = () => [...sel.selected].map((id) => byId.get(id)).filter(Boolean) as Experiment[];
  const clearSelection = () => dispatch({ type: "clear" });

  async function moveOne(name: string, to: "drive" | "local") {
    await api.moveExperiment(name, to, fullVerify);
    for (;;) {
      await new Promise((r) => setTimeout(r, 600));
      const jb = await api.moveStatus(name);
      if (jb.state === "done") return;
      if (jb.state === "error") throw new Error(jb.error ?? "move failed");
      if (jb.state === "idle") return;
    }
  }

  async function bulkMove(to: "drive" | "local") {
    // only runs on the opposite side can move that direction; skip the rest to avoid "already there"
    const targets = selectedItems().filter((e) => (to === "drive" ? e.library !== "drive" : e.library === "drive"));
    if (targets.length === 0) { setErr(`nothing selected is on ${to === "drive" ? "local" : "the drive"}`); return; }
    setBulkBusy(true); setErr(null);
    let done = 0; const fails: string[] = [];
    for (const e of targets) {
      setBulkProgress(`moving ${done + 1}/${targets.length}…`);
      try { await moveOne(e.name, to); } catch (err) { fails.push(`${e.name}: ${err}`); }
      done += 1;
    }
    setBulkBusy(false); setBulkProgress(null); clearSelection(); load();
    if (fails.length) setErr(`${fails.length} move(s) failed — ${fails[0]}`);
  }

  async function bulkStar(on: boolean) {
    setBulkBusy(true); setErr(null);
    const fails: string[] = [];
    for (const e of selectedItems()) {
      try {
        await api.setLabels(e.name, { starred: on, tags: e.tags ?? [], library: e.library === "drive" ? "drive" : "local" });
      } catch (err) { fails.push(String(err)); }
    }
    setBulkBusy(false); clearSelection(); load();
    if (fails.length) setErr(`${fails.length} update(s) failed`);
  }

  async function bulkAddTags(add: string[]) {
    setBulkTagOpen(false);
    if (add.length === 0) return;
    setBulkBusy(true); setErr(null);
    const fails: string[] = [];
    for (const e of selectedItems()) {
      try {
        await api.setLabels(e.name, {
          starred: !!e.starred, tags: mergeTags(e.tags ?? [], add),
          library: e.library === "drive" ? "drive" : "local",
        });
      } catch (err) { fails.push(String(err)); }
    }
    setBulkBusy(false); clearSelection(); load();
    if (fails.length) setErr(`${fails.length} tag update(s) failed`);
  }

  async function bulkDelete() {
    const targets = selectedItems();
    if (targets.length === 0) return;
    const names = targets.map((e) => e.name).join("\n");
    if (!window.confirm(`Delete ${targets.length} run(s) for good?\n\n${names}\n\nThis removes each run folder entirely. There is no undo.`)) return;
    setBulkBusy(true); setErr(null);
    const fails: string[] = [];
    for (const e of targets) {
      try { await api.deleteExperiment(e.name); } catch (err) { fails.push(String(err)); }
    }
    setBulkBusy(false); clearSelection(); load();
    if (fails.length) setErr(`${fails.length} delete(s) failed`);
  }

  return (
    <div className="page-body wide">
      <div className="exp-head">
        <span>{items ? (filtering ? `${shown.length} / ${summaryLabel(breakdown, driveConnected)}` : summaryLabel(breakdown, driveConnected)) : "loading…"}</span>
        <span className="right">
          <button className={`secondary${selecting ? " active" : ""}`} onClick={() => { setSelecting((s) => !s); clearSelection(); }} title="Select multiple runs for bulk actions">
            {selecting ? "done selecting" : "select"}
          </button>
          <label className={`chip-toggle${starredOnly ? " on" : ""}`} title="Show starred runs only">
            <input type="checkbox" checked={starredOnly} onChange={(e) => setStarredP(e.target.checked)} /> ★ starred
          </label>
          {driveConnected && (
            <label className="hint" title="Checksum every file (SHA-256) when moving a run. Slower, but catches silent corruption between machines." style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
              <input type="checkbox" checked={fullVerify} onChange={(e) => toggleFullVerify(e.target.checked)} /> full verify
            </label>
          )}
          <input type="text" placeholder="filter (name or tag)" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 170 }} />
          <select value={sort} onChange={(e) => setSortP(e.target.value as Sort)}>
            <option value="newest">newest</option>
            <option value="starred">starred first</option>
            <option value="name">name</option>
            <option value="duration">duration</option>
          </select>
          <button className="secondary" onClick={() => api.revealRoot().then((r) => { if (!r.ok) setErr(`${r.error ?? "reveal failed"} — ${r.path}`); }).catch((e) => setErr(String(e)))}>
            open folder
          </button>
        </span>
      </div>

      {tagFilter.length > 0 && (
        <div className="filter-chips">
          <span className="hint">tags:</span>
          {tagFilter.map((t) => (
            <button key={t} className="tag-chip on" title="remove filter" onClick={() => setTagsP(tagFilter.filter((x) => x !== t))}>{t} ×</button>
          ))}
          {universe.filter((t) => !tagFilter.includes(t)).slice(0, 12).map((t) => (
            <button key={t} className="tag-chip" onClick={() => addTagFilter(t)}>{t}</button>
          ))}
        </div>
      )}
      {tagFilter.length === 0 && universe.length > 0 && (
        <div className="filter-chips">
          <span className="hint">tags:</span>
          {universe.slice(0, 12).map((t) => (
            <button key={t} className="tag-chip" onClick={() => addTagFilter(t)}>{t}</button>
          ))}
        </div>
      )}

      {err && <div className="errbox">{err}</div>}
      {items && items.length === 0 && <div className="muted">No experiments yet. Record one from the live view.</div>}
      {items && items.length > 0 && shown.length === 0 && <div className="muted">No experiments match the filter.</div>}
      <div className="exp-grid">
        {shown.map((e) => {
          const id = cardId(e);
          return (
            <ExperimentCard
              key={id} exp={e} onOpen={() => onOpen(e.name)} onChanged={load}
              driveConnected={driveConnected} fullVerify={fullVerify} universe={universe}
              selecting={selecting} selected={sel.selected.has(id)}
              onToggleSelect={(ev) => dispatch(ev.shiftKey ? { type: "range", name: id, order: shownIds } : { type: "toggle", name: id })}
              onFilterTag={addTagFilter}
            />
          );
        })}
      </div>

      {selecting && sel.selected.size > 0 && (
        <>
          <SelectionBar
            count={sel.selected.size} driveConnected={driveConnected} busy={bulkBusy} progress={bulkProgress}
            onMove={bulkMove} onTag={() => setBulkTagOpen(true)} onStar={bulkStar} onDelete={bulkDelete}
            onSelectAll={() => dispatch({ type: "selectAll", names: shownIds })} onClear={() => { clearSelection(); setSelecting(false); }}
          />
          {bulkTagOpen && (
            <div className="bulk-tag-pop">
              <TagPopover tags={[]} universe={universe} addOnly onChange={bulkAddTags} onClose={() => setBulkTagOpen(false)} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
