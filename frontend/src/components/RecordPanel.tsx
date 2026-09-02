import { useEffect, useState } from "react";
import { api, type RecordingStatus } from "../lib/api.ts";

const FIELDS: { key: string; label: string; type?: "number" }[] = [
  { key: "operator", label: "Operator" },
  { key: "sample_id", label: "Sample ID" },
  { key: "material", label: "Material" },
  { key: "dopant", label: "Dopant" },
  { key: "dopant_concentration", label: "Dopant conc." },
  { key: "rf_frequency_mhz", label: "RF freq (MHz)", type: "number" },
  { key: "rf_forward_power_w", label: "RF fwd (W)", type: "number" },
  { key: "electrode_gap_mm", label: "Gap (mm)", type: "number" },
  { key: "notes", label: "Notes" },
];

export function RecordPanel({ acquiring, rois }: { acquiring: boolean; rois: unknown[] }) {
  const [name, setName] = useState("Run");
  const [meta, setMeta] = useState<Record<string, string>>({ material: "PA12", rf_frequency_mhz: "13.56" });
  const [status, setStatus] = useState<RecordingStatus>({ state: "idle" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [withVisible, setWithVisible] = useState(true);

  useEffect(() => {
    const tick = async () => { try { setStatus(await api.recordingStatus()); } catch { /* keep last */ } };
    void tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const recording = status.state === "recording";
  const vis = status.visible;
  const visibleAvailable = !!vis && vis.state !== "unavailable";

  async function start() {
    setBusy(true); setErr(null);
    try {
      const m: Record<string, unknown> = {};
      for (const f of FIELDS) {
        const v = meta[f.key];
        if (v !== undefined && v !== "") m[f.key] = f.type === "number" ? Number(v) : v;
      }
      await api.recordingStart(name, m, withVisible && visibleAvailable, rois);
      setStatus(await api.recordingStatus());
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function stop() {
    setBusy(true); setErr(null);
    try { await api.recordingStop(); setStatus(await api.recordingStatus()); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  const low = (status.free_space_gb ?? Infinity) < (status.min_free_gb ?? 2);

  const [markName, setMarkName] = useState("");
  const [markNote, setMarkNote] = useState("");
  const [lastMark, setLastMark] = useState<string | null>(null);
  async function mark(label: string) {
    const nm = label.trim();
    if (!nm) return;
    setErr(null);
    try {
      const ev = await api.recordingEvent(nm, markNote.trim() || undefined);
      setLastMark(`${nm} @ frame ${ev.frame_id ?? "?"}`);
      setMarkName(""); setMarkNote("");
    } catch (e) { setErr(String(e)); }
  }

  return (
    <>
      <div className="row">
        {!recording ? (
          <>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="experiment name" style={{ width: 140 }} />
            <button className="primary" disabled={!acquiring || busy} onClick={start} title={acquiring ? "" : "connect a camera first"}>● Record</button>
            <button className="secondary" onClick={() => setShowForm(!showForm)}>{showForm ? "Hide metadata" : "Metadata"}</button>
            <label className="hint" title={visibleAvailable ? "Also record the visible camera (RTSP /avc/ch1, H.264 stream copy) as visible.mp4" : `visible camera unavailable: ${vis?.reason ?? "no status yet"}`}>
              <input type="checkbox" checked={withVisible && visibleAvailable} disabled={!visibleAvailable} onChange={(e) => setWithVisible(e.target.checked)} /> visible video
            </label>
          </>
        ) : (
          <button className="danger" disabled={busy} onClick={stop}>■ Stop</button>
        )}
      </div>
      {recording && (
        <>
          <div className="row" aria-label="event marks">
            <button className="secondary" onClick={() => mark("RF ON")}>RF ON</button>
            <button className="secondary" onClick={() => mark("RF OFF")}>RF OFF</button>
            <input type="text" value={markName} placeholder="custom mark" style={{ width: 110 }} onChange={(e) => setMarkName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void mark(markName); }} />
            <button className="secondary" disabled={!markName.trim()} onClick={() => mark(markName)}>mark</button>
          </div>
          <div className="row">
            <input type="text" value={markNote} placeholder="note (optional)" style={{ flex: 1, minWidth: 120 }} onChange={(e) => setMarkNote(e.target.value)} />
          </div>
          {lastMark && <div className="hint">marked {lastMark}</div>}
        </>
      )}
      {showForm && !recording && (
        <div className="kv">
          {FIELDS.map((f) => (
            <label key={f.key} style={{ display: "contents" }}>
              <span>{f.label}</span>
              <input type={f.type ?? "text"} value={meta[f.key] ?? ""} onChange={(e) => setMeta({ ...meta, [f.key]: e.target.value })} style={{ width: 120 }} />
            </label>
          ))}
        </div>
      )}
      <div className="kv">
        <span>ROIs saved</span><span className="v">{rois.length}</span>
        <span>State</span><span className="v">{recording ? <span className="badge rec">● REC</span> : status.state}</span>
        {recording && (<>
          <span>Written</span><span className="v">{status.frames_written ?? 0} / {status.frames_received ?? 0}</span>
          <span>Recorded fps</span><span className="v">{status.recorded_fps ? status.recorded_fps.toFixed(1) : "—"}</span>
          <span>Duration</span><span className="v">{(status.duration_s ?? 0).toFixed(1)} s</span>
          <span>Queue</span><span className="v">{status.queue_depth ?? 0}</span>
        </>)}
        {vis && vis.state !== "unavailable" && vis.state !== "idle" && (<>
          <span>Visible</span><span className="v" style={{ color: vis.state === "error" ? "var(--err)" : undefined }}>{vis.state}{vis.error ? ` · ${vis.error}` : ""}</span>
        </>)}
        <span>Rec. dropped</span><span className="v" style={{ color: (status.queue_dropped ?? 0) > 0 ? "var(--err)" : undefined }}>{status.queue_dropped ?? 0}</span>
        <span>Camera gaps</span><span className="v" style={{ color: (status.frame_id_gaps ?? 0) > 0 ? "var(--warn)" : undefined }}>{status.frame_id_gaps ?? 0}</span>
        <span>Free disk</span><span className="v" style={{ color: low ? "var(--err)" : undefined }}>{status.free_space_gb != null ? `${status.free_space_gb.toFixed(1)} GB` : "—"}</span>
      </div>
      {status.experiment_dir && <div className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{status.experiment_dir}</div>}
      {status.error && <div className="errbox">{status.error}</div>}
      {err && <div className="errbox">{err}</div>}
      {low && <div className="warnbox">Free space is below the recorder's minimum; recording needs about 1 GB per minute uncompressed.</div>}
    </>
  );
}
