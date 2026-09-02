import { useEffect, useState } from "react";
import { api, type Experiment } from "../lib/api.ts";

export function ExperimentsPage({ onOpen }: { onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Experiment[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.experiments().then(setItems).catch((e) => setErr(String(e))); }, []);
  return (
    <div className="setup">
      <div className="card">
        <h2>Recorded experiments</h2>
        {err && <div className="errbox">{err}</div>}
        {items && items.length === 0 && <div className="muted">No experiments yet. Record one from the Live view.</div>}
        {items && items.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr className="muted" style={{ textAlign: "left" }}><th>Name</th><th>Frames</th><th>Duration</th><th>Format</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {items.map((e) => {
                const n = (e as unknown as { n_frames?: number }).n_frames ?? e.frames_on_disk;
                const dur = (e as unknown as { duration_s?: number }).duration_s;
                const fmt = (e as unknown as { ir_format?: string }).ir_format;
                return (
                  <tr key={e.name} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={{ padding: "6px 4px" }}><code>{e.name}</code></td>
                    <td>{n}</td>
                    <td>{dur != null ? `${dur.toFixed(1)} s` : "—"}</td>
                    <td>{fmt ?? "—"}</td>
                    <td>{e.complete ? <span style={{ color: "var(--live)" }}>complete</span> : <span style={{ color: "var(--warn)" }}>INCOMPLETE</span>}</td>
                    <td><button className="primary" disabled={!n} onClick={() => onOpen(e.name)}>Open</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
