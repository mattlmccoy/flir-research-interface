import { useMemo, useState } from "react";
import { bulkTitles } from "../lib/organize.ts";

// Bulk rename for the selected runs: one base name, optionally numbered in recording order, with a
// live preview of every new name before anything is written. Display names only — the run folders
// keep their names; notes, stars and tags are untouched. A blank name clears the display names.
export function BulkRenamePopover({
  items, onApply, onClose,
}: {
  items: { name: string; started_utc?: string | null; title?: string | null }[];
  onApply: (titles: { name: string; title: string }[]) => void;
  onClose: () => void;
}) {
  const [base, setBase] = useState("");
  const [numbered, setNumbered] = useState(true);
  const plan = useMemo(() => bulkTitles(items, base, numbered), [items, base, numbered]);
  const clearing = base.trim() === "";
  const shown = plan.slice(0, 6);
  return (
    <div className="bulk-rename" role="dialog" aria-label="rename selected runs">
      <div className="hint">Rename {items.length} run{items.length === 1 ? "" : "s"} — display names only; folders keep their names.</div>
      <input autoFocus type="text" value={base} maxLength={110} placeholder="name, e.g. Doped coupon"
        aria-label="new name for the selected runs" onChange={(e) => setBase(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); if (e.key === "Enter") onApply(plan); }} />
      <label className="hint" style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={numbered} onChange={(e) => setNumbered(e.target.checked)} />
        number them 1, 2, 3… in recording order
      </label>
      <ol className="bulk-rename-preview" aria-label="preview">
        {shown.map((p) => (
          <li key={p.name}><span className="folder-name">{p.name}</span> → {p.title || <em>folder name (name cleared)</em>}</li>
        ))}
        {plan.length > shown.length && <li className="hint">…and {plan.length - shown.length} more</li>}
      </ol>
      <div className="actions-row">
        <button className={clearing ? "danger" : "primary"} disabled={items.length === 0} onClick={() => onApply(plan)}>
          {clearing ? "clear names" : `rename ${items.length}`}
        </button>
        <button className="secondary" onClick={onClose}>cancel</button>
      </div>
    </div>
  );
}
