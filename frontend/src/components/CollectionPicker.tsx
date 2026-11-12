import { useEffect, useRef, useState } from "react";
import { api, type CollectionsDoc } from "../lib/api.ts";
import { collectionNameError, collectionsStatus, pickerEntries, PICKER_LOCK_MESSAGE } from "../lib/collections.ts";

/** The collection picker on the experiments page: the operator's selection (shared by every
 *  browser), the Unsorted top level, the folders it leaves alone, and an inline "add" form.
 *  Locked while a recording or armed trigger is active (the operator answers 409 then). */
export function CollectionPicker({ doc, error = null, locked, onDoc }: { doc: CollectionsDoc | null; error?: string | null; locked: boolean; onDoc: (d: CollectionsDoc) => void }) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const close = () => { setOpen(false); setAdding(false); setDraft(""); setErr(null); };
  useEffect(() => { if (locked) close(); }, [locked]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function act(fn: () => Promise<CollectionsDoc>) {
    setBusy(true); setErr(null);
    try { onDoc(await fn()); close(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const select = (name: string) => act(() => api.selectCollection(name));
  // a new collection is selected right away; it never renames or moves an existing one
  const add = (name: string) => act(async () => { await api.addCollection(name); return api.selectCollection(name); });

  const draftErr = draft === "" ? null : collectionNameError(draft);
  const entries = doc ? pickerEntries(doc) : [];
  const label = collectionsStatus(doc, error);

  return (
    <div className="coll-picker" ref={box}>
      <button type="button" className={`coll-btn${doc && !doc.selected ? " unset" : ""}${!doc && error ? " error" : ""}`} disabled={!doc || locked}
        aria-haspopup="listbox" aria-expanded={open}
        title={locked ? PICKER_LOCK_MESSAGE : "The user or project new runs record into; the list below shows its runs"}
        onClick={() => (open ? close() : setOpen(true))}>
        <span className="k">collection</span><span className="nm">{label}</span><span aria-hidden>▾</span>
      </button>
      {open && doc && (
        <div className="coll-menu" role="listbox" aria-label="collections">
          {entries.length === 0 && <div className="hint">No collections yet. Add one below.</div>}
          {entries.map((e, i) => (
            <button key={`${i}:${e.value}`} type="button" role="option" aria-selected={!e.disabled && e.value === doc.selected}
              className={`coll-opt${!e.disabled && e.value === doc.selected ? " on" : ""}`} disabled={e.disabled || busy}
              title={e.disabled ? `${e.label}: ${e.note}` : undefined} onClick={() => select(e.value)}>
              <span className="nm">{e.label}</span>{e.note && <span className="note">{e.note}</span>}
            </button>
          ))}
          <div className="coll-add">
            {!adding
              ? <button type="button" className="linkish" onClick={() => setAdding(true)}>+ new collection</button>
              : <>
                <div className="row">
                  <input autoFocus type="text" value={draft} placeholder="e.g. mattmccoy" aria-label="new collection name"
                    aria-invalid={!!draftErr} onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && draft && !draftErr && !busy) void add(draft); }} />
                  <button type="button" className="primary" disabled={!draft || !!draftErr || busy} onClick={() => add(draft)}>add</button>
                </div>
                {draftErr ? <div className="bad" role="alert">{draftErr}</div>
                  : <div className="hint">{draft ? `a new, empty collection ${draft}/ that new runs record into; existing runs stay where they are` : "lowercase letters, digits, '-' and '_'"}</div>}
              </>}
          </div>
          {err && <div className="bad" role="alert">{err}</div>}
        </div>
      )}
    </div>
  );
}

/** "Recording to: <collection>", and why Record / Arm are off when no collection is picked. */
export function RecordingTo({ name, reason }: { name: string; reason: string | null }) {
  return (
    <div className={`recording-to${reason ? " blocked" : ""}`}>
      <div><span className="k">Recording to:</span> <b>{name}</b></div>
      {reason && <div className="warnbox" role="alert">{reason} (pick who's using this from the menu at the top right)</div>}
    </div>
  );
}
