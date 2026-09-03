import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { ExperimentCard } from "./ExperimentCard.tsx";

type Sort = "newest" | "name" | "duration";

export function ExperimentsPage({ onOpen }: { onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Experiment[] | null>(null);
  const totalBytes = items ? items.reduce((a, e) => a + (e.size_bytes ?? 0), 0) : 0;
  const [err, setErr] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("newest");
  const [q, setQ] = useState("");
  const load = useCallback(() => {
    api.experiments().then(setItems).catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const shown = useMemo(() => {
    if (!items) return [];
    const f = q.trim().toLowerCase();
    const list = items.filter((e) => !f || e.name.toLowerCase().includes(f) || JSON.stringify(e.experiment ?? {}).toLowerCase().includes(f));
    return [...list].sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "duration") return (b.duration_s ?? 0) - (a.duration_s ?? 0);
      // newest: by started_utc descending, falling back to name (which sorts newest-first
      // for this project's timestamp-prefixed names) when either side lacks started_utc.
      if (a.started_utc && b.started_utc) {
        const byStart = b.started_utc.localeCompare(a.started_utc);
        if (byStart !== 0) return byStart;
      }
      return b.name.localeCompare(a.name);
    });
  }, [items, sort, q]);
  const filtering = q.trim().length > 0;

  return (
    <div className="page-body wide">
      <div className="exp-head">
        <span>{items ? (filtering ? `${shown.length} / ${items.length} experiments` : `${items.length} experiments`) : "loading…"}{items && totalBytes > 0 ? ` · ${(totalBytes / 1e9).toFixed(2)} GB on disk` : ""}</span>
        <span className="right">
          <input type="text" placeholder="filter" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 160 }} />
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="newest">newest</option>
            <option value="name">name</option>
            <option value="duration">duration</option>
          </select>
          <button
            className="secondary"
            onClick={() =>
              api
                .revealRoot()
                .then((r) => {
                  if (!r.ok) setErr(`${r.error ?? "reveal failed"} — ${r.path}`);
                })
                .catch((e) => setErr(String(e)))
            }
          >
            open folder
          </button>
        </span>
      </div>
      {err && <div className="errbox">{err}</div>}
      {items && items.length === 0 && <div className="muted">No experiments yet. Record one from the live view.</div>}
      {items && items.length > 0 && shown.length === 0 && <div className="muted">No experiments match the filter.</div>}
      <div className="exp-grid">
        {shown.map((e) => (
          <ExperimentCard key={e.name} exp={e} onOpen={() => onOpen(e.name)} onChanged={load} />
        ))}
      </div>
    </div>
  );
}
