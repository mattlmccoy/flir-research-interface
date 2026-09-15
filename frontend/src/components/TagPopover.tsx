import { useState } from "react";
import { normalizeTag, suggestTags } from "../lib/organize.ts";

// Autocomplete tag editor. `tags` are the current tags; `universe` is every tag in use (for
// suggestions). onChange gives the full new tag set. Used for one card and (addOnly) for bulk add.
export function TagPopover({ tags, universe, onChange, onClose, addOnly = false }: {
  tags: string[];
  universe: string[];
  onChange: (next: string[]) => void;
  onClose?: () => void;
  addOnly?: boolean;
}) {
  const [q, setQ] = useState("");
  const add = (t: string) => {
    const n = normalizeTag(t);
    if (!n) return;
    if (!tags.some((x) => x.toLowerCase() === n.toLowerCase())) onChange([...tags, n]);
    setQ("");
  };
  const remove = (t: string) => onChange(tags.filter((x) => x !== t));
  const sugg = suggestTags(universe, q, tags);
  return (
    <div className="tag-popover" role="dialog" onKeyDown={(e) => { if (e.key === "Escape") onClose?.(); }}>
      {!addOnly && tags.length > 0 && (
        <div className="tag-chips">
          {tags.map((t) => (
            <span key={t} className="tag-chip">
              {t}<button aria-label={`remove ${t}`} onClick={() => remove(t)}>×</button>
            </span>
          ))}
        </div>
      )}
      <input
        autoFocus type="text" placeholder="add tag…" value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) { e.preventDefault(); add(q); } }}
      />
      {sugg.length > 0 && (
        <div className="tag-suggest">
          {sugg.map((t) => (
            <button key={t} className="tag-suggest-item" onClick={() => add(t)}>{t}</button>
          ))}
        </div>
      )}
    </div>
  );
}
