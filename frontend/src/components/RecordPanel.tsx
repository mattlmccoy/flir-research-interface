import { markForKey } from "../lib/delta.ts";
import { useEffect, useState } from "react";
import { api, DEFAULT_PROFILE, type Profile, type RecordingStatus } from "../lib/api.ts";
import { ArmPanel } from "./ArmPanel.tsx";
import type { Roi } from "../lib/roi.ts";


export function RecordPanel({ acquiring, rois }: { acquiring: boolean; rois: Roi[] }) {
  const [name, setName] = useState("Run");
  const [meta, setMeta] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  useEffect(() => { api.profile().then(setProfile).catch(() => undefined); }, []);
  const FIELDS = profile.fields;
  const [status, setStatus] = useState<RecordingStatus>({ state: "idle" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [withVisible, setWithVisible] = useState(true);
  const [nucHold, setNucHold] = useState(true);
  const [everyNth, setEveryNth] = useState(1);

  useEffect(() => {
    const tick = async () => { try { setStatus(await api.recordingStatus()); } catch { /* keep last */ } };
    void tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const recording = status.state === "recording";
  const armed = status.armed ?? null;
  async function arm(trigger: unknown) {
    setBusy(true); setErr(null);
    try {
      const m: Record<string, unknown> = {};
      for (const f of FIELDS) { const v = meta[f.key]; if (v !== undefined && v !== "") m[f.key] = f.type === "number" ? Number(v) : v; }
      await api.recordingArm(name, m, withVisible && visibleAvailable, rois, trigger, nucHold);
      setStatus(await api.recordingStatus());
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function disarm() {
    setBusy(true); setErr(null);
    try { await api.recordingDisarm(); setStatus(await api.recordingStatus()); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function startNow() {
    setBusy(true); setErr(null);
    try { await api.recordingArmStart(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
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
      await api.recordingStart(name, m, withVisible && visibleAvailable, rois, nucHold, everyNth);
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
  useEffect(() => {
    if (!recording) return;
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      const inInput = !!tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable);
      const m = markForKey(e.key, inInput || e.metaKey || e.ctrlKey || e.altKey, profile.marks);
      if (!m) return;
      e.preventDefault();
      void mark(m);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording, markNote, profile]);
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
      {(armed || !recording) && <ArmPanel rois={rois} armed={armed} recording={recording} disabled={!acquiring} busy={busy} onArm={arm} onDisarm={disarm} onStartNow={startNow} />}
      <div className="row">
        {!recording && !armed ? (
          <>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="experiment name" style={{ width: 140 }} />
            <button className="primary" disabled={!acquiring || busy} onClick={start} title={acquiring ? "" : "connect a camera first"}>● Record</button>
            <button className="secondary" onClick={() => setShowForm(!showForm)}>{showForm ? "Hide metadata" : "Metadata"}</button>
            <label className="hint" title={visibleAvailable ? "Also record the visible camera (RTSP /avc/ch1, H.264 stream copy) as visible.mp4" : `visible camera unavailable: ${vis?.reason ?? "no status yet"}`}>
              <input type="checkbox" checked={withVisible && visibleAvailable} disabled={!visibleAvailable} onChange={(e) => setWithVisible(e.target.checked)} /> visible video
            </label>
            <label className="hint" title="Run a NUC right before the recording, then hold NUCMode=Off until stop so the camera never freezes its image mid-run (~2 s per NUC). The previous mode is restored at stop.">
              <input type="checkbox" checked={nucHold} onChange={(e) => setNucHold(e.target.checked)} /> NUC before, none during
            </label>
            <label className="hint" title="Periodic (time-lapse) recording: keep every Nth frame. 1 = every frame (30 fps); 30 = one frame per second; 1800 = one per minute. Skipped frames are intentional and do not count as drops.">
              every <input type="number" min={1} max={100000} step={1} value={everyNth} style={{ width: 64 }} onChange={(e) => setEveryNth(Math.max(1, Math.floor(Number(e.target.value) || 1)))} /> frame{everyNth === 1 ? "" : "s"}{everyNth > 1 ? <small className="muted"> ≈ {(30 / everyNth).toPrecision(2)} fps</small> : null}
            </label>
          </>
        ) : recording && !armed ? (
          <button className="danger" disabled={busy} onClick={stop}>■ Stop</button>
        ) : null}
      </div>
      {recording && (
        <>
          <div className="row" aria-label="event marks">
            {profile.marks.map((m) => (
              <button key={m.label} className="secondary" onClick={() => mark(m.label)} title={m.key ? `keyboard: ${m.key}` : undefined}>{m.label}{m.key ? <small className="muted"> {m.key}</small> : null}</button>
            ))}
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
          <span className="hint" style={{ gridColumn: "1 / -1" }}>profile: <b>{profile.name}</b> · fields and mark buttons are set on the setup page</span>
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
        <span title="consecutive frames with identical pixels: the camera repeats its last image during a NUC (~2 s). Kept in the record, logged in events.json as frozen_frames">Frozen frames</span><span className="v" style={{ color: (status.repeated_frames ?? 0) > 0 ? "var(--warn)" : undefined }}>{status.repeated_frames ?? 0}</span>
        <span>Camera gaps</span><span className="v" style={{ color: (status.frame_id_gaps ?? 0) > 0 ? "var(--warn)" : undefined }}>{status.frame_id_gaps ?? 0}</span>
        <span>Free disk</span><span className="v" style={{ color: low ? "var(--err)" : undefined }}>{status.free_space_gb != null ? `${status.free_space_gb.toFixed(1)} GB` : "—"}</span>
      </div>
      {recording && vis?.state === "error" && (
        <div className="errbox" role="alert">
          <b>Visible video failed</b> — {vis.error ?? "ffmpeg stopped"}. The thermal recording continues; this run will have no visible.mp4{(vis.restarts ?? 0) > 0 ? ` (retried ${vis.restarts}×)` : ""}.
        </div>
      )}
      {recording && vis?.state === "recording" && (vis.restarts ?? 0) > 0 && <div className="warnbox">Visible stream needed {vis.restarts} retr{vis.restarts === 1 ? "y" : "ies"} to open; the first {vis.restarts} second{vis.restarts === 1 ? "" : "s"} may be missing from visible.mp4.</div>}
      {status.experiment_dir && <div className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{status.experiment_dir}</div>}
      {status.error && <div className="errbox">{status.error}</div>}
      {err && <div className="errbox">{err}</div>}
      {low && <div className="warnbox">Free space is below the recorder's minimum; recording needs about 1 GB per minute uncompressed.</div>}
    </>
  );
}
