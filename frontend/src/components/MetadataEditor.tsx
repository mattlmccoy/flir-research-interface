import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";
import { parseValue } from "../lib/metadata.ts";

interface Props { name: string; experiment: Record<string, unknown>; onSaved: () => void; }

type Row = { key: string; value: string };

function toRows(exp: Record<string, unknown>): Row[] {
  return Object.entries(exp).filter(([k]) => k !== "name").map(([k, v]) => ({ key: k, value: v == null ? "" : String(v) }));
}

/** Edits the operator-entered `experiment` block of metadata.json after the fact (Milestone 8). */
export function MetadataEditor({ name, experiment, onSaved }: Props) {
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<Row[]>(toRows(experiment));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const key = JSON.stringify(experiment);
  useEffect(() => { setRows(toRows(experiment)); }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    setBusy(true); setErr(null);
    try {
      const patch: Record<string, unknown> = {};
      for (const r of rows) {
        const k = r.key.trim();
        if (!k || k === "name") continue;
        patch[k] = parseValue(r.value);
      }
      for (const k of Object.keys(experiment)) if (k !== "name" && !rows.some((r) => r.key.trim() === k)) patch[k] = null;
      await api.patchMetadata(name, patch);
      setEditing(false);
      onSaved();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  if (!editing) {
    return (
      <>
        <div className="kv">
          {Object.entries(experiment).filter(([k]) => k !== "name").map(([k, v]) => [
            <span key={`k-${k}`}>{k}</span>,
            <span key={`v-${k}`} className="v plain">{String(v)}</span>,
          ])}
        </div>
        <div className="row"><button className="secondary" onClick={() => setEditing(true)}>edit metadata</button></div>
        {err && <div className="errbox">{err}</div>}
      </>
    );
  }
  return (
    <>
      <div className="kv">
        {rows.map((r, i) => [
          <input key={`k${i}`} type="text" value={r.key} aria-label="field" style={{ width: 110 }}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />,
          <span key={`v${i}`} className="v plain" style={{ display: "flex", gap: 4 }}>
            <input type="text" value={r.value} aria-label="value" style={{ flex: 1, minWidth: 60 }}
              onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
            <button className="secondary" aria-label={`remove ${r.key}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
          </span>,
        ])}
      </div>
      <div className="row">
        <button className="secondary" onClick={() => setRows([...rows, { key: "", value: "" }])}>+ field</button>
        <button className="primary" disabled={busy} onClick={save}>save</button>
        <button className="secondary" disabled={busy} onClick={() => { setRows(toRows(experiment)); setEditing(false); }}>cancel</button>
      </div>
      <div className="hint">Edits are logged in metadata.json; camera and conversion blocks stay as recorded.</div>
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
