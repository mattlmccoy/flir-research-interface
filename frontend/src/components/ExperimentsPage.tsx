import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { ExperimentCard } from "./ExperimentCard.tsx";

type Sort = "newest" | "name" | "duration";

export function ExperimentsPage({ onOpen }: { onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Experiment[] | null>(null);
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
    return [...list].sort((a, b) =>
      sort === "name" ? a.name.localeCompare(b.name) : sort === "duration" ? (b.duration_s ?? 0) - (a.duration_s ?? 0) : b.name.localeCompare(a.name),
    );
  }, [items, sort, q]);

  return (
    <div className="page-body">
      <div className="exp-head">
        <span>{items ? `${items.length} experiments` : "loading…"}</span>
        <span className="right">
          <input type="text" placeholder="filter" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 160 }} />
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="newest">newest</option>
            <option value="name">name</option>
            <option value="duration">duration</option>
          </select>
          <button className="secondary" onClick={() => void api.revealRoot().catch((e) => setErr(String(e)))}>
            open folder
          </button>
        </span>
      </div>
      {err && <div className="errbox">{err}</div>}
      {items && items.length === 0 && <div className="muted">No experiments yet. Record one from the live view.</div>}
      <div className="exp-grid">
        {shown.map((e) => (
          <ExperimentCard key={e.name} exp={e} onOpen={() => onOpen(e.name)} onChanged={load} />
        ))}
      </div>
    </div>
  );
}
