import { useState } from "react";
import { api, type Experiment, type Previews } from "../lib/api.ts";
import { formatSeconds, keyframeBackgroundPosition, keyframeIndex } from "../lib/keyframes.ts";
import { hasRois, loadRois, roisDifferFromStored } from "../lib/roi.ts";

interface Props { exp: Experiment; onOpen: () => void; onChanged: () => void; driveConnected?: boolean; }

const roiStorage: Storage | null = (() => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; } })();

export function ExperimentCard({ exp, onOpen, onChanged, driveConnected = false }: Props) {
  // Flag runs whose ROIs have been edited since their exports were built: the run has a saved
  // working set that differs from the ROIs stored (and exported) with the recording.
  const scope = `exp.${exp.name}`;
  const roisDiffer = hasRois(roiStorage, scope) && roisDifferFromStored(loadRois(roiStorage, scope).rois, exp.rois ?? null);
  const [k, setK] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [move, setMove] = useState<{ done: number; total: number } | null>(null);
  const onDrive = exp.library === "drive";

  // Offload to the drive (or bring back), copy → verify → delete, with a progress bar.
  async function moveTo(to: "drive" | "local") {
    setBusy(true); setNote(null); setMove({ done: 0, total: 0 });
    try {
      await api.moveExperiment(exp.name, to);
      for (;;) {
        await new Promise((r) => setTimeout(r, 600));
        const jb = await api.moveStatus(exp.name);
        setMove({ done: jb.done ?? 0, total: jb.total ?? 0 });
        if (jb.state === "done") { onChanged(); break; }
        if (jb.state === "error") { setNote(jb.error ?? "move failed"); break; }
        if (jb.state === "idle") break;
      }
    } catch (e) { setNote(String(e)); } finally { setBusy(false); setMove(null); }
  }
  // The regenerate response is authoritative the instant it comes back — don't wait on the
  // parent's refetch (onChanged) to see the new preview, in case it's slow or the parent's
  // list is stale for another reason.
  const [local, setLocal] = useState<Previews | null>(null);
  const previews = exp.previews ?? local;
  const kf = previews?.keyframes;
  const count = kf?.count ?? 0;
  const n = exp.n_frames ?? exp.frames_on_disk;
  const meta = exp.experiment ?? {};
  // content-addressed cache key: regenerated previews change the sha, so the URL changes
  const v = previews ? `${previews.preview.sha256.slice(0, 12)}` : "";
  const kv = previews ? `${previews.keyframes.sha256.slice(0, 12)}` : "";
  const dropped = (exp.manifest as { queue_dropped?: number } | null)?.queue_dropped ?? 0;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!count) return;
    const r = e.currentTarget.getBoundingClientRect();
    setK(keyframeIndex(e.clientX - r.left, r.width, count));
  }
  async function remove(e: React.MouseEvent) {
    e.stopPropagation();
    const ok = window.confirm(`Delete "${exp.name}" for good?\n\nThis removes the whole run folder (thermal.zarr, visible video, exports). There is no undo.`);
    if (!ok) return;
    setBusy(true); setNote(null);
    try { await api.deleteExperiment(exp.name); onChanged(); } catch (err) { setNote(String(err)); } finally { setBusy(false); }
  }
  async function reveal(e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(true);
    setNote(null);
    try {
      const r = await api.reveal(exp.name);
      if (!r.ok) setNote(`${r.error ?? "reveal failed"} — ${r.path}`);
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(false);
    }
  }
  async function exportH5(e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(true);
    setNote(null);
    try {
      const r = await api.exportHdf5(exp.name);
      setNote(`HDF5 written (${(r.size_bytes / 1e6).toFixed(1)} MB): ${r.path}`);
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(false);
    }
  }
  async function regen(e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(true);
    setNote(null);
    try {
      setLocal(await api.regeneratePreviews(exp.name));
      onChanged();
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(false);
    }
  }

  const unitLabel = previews?.units === "counts" ? " (raw counts)" : "";
  return (
    <div className="exp-card">
      <div className="thumb" onMouseMove={onMove} onMouseLeave={() => setK(null)} onClick={onOpen} title="open">
        {previews ? (
          <>
            <img src={`${api.previewUrl(exp.name)}?v=${v}`} alt="" />
            {k !== null && kf && (
              <div
                className="kf"
                style={{
                  backgroundImage: `url(${api.keyframesUrl(exp.name)}?v=${kv})`,
                  backgroundPosition: keyframeBackgroundPosition(k, count),
                  backgroundSize: `${count * 100}% 100%`,
                }}
              />
            )}
            <span className="t">
              {k !== null && kf ? `t = ${formatSeconds(kf.t_s[k] ?? 0)}${unitLabel}` : `${n} frames · ${exp.duration_s != null ? formatSeconds(exp.duration_s) : "—"}`}
            </span>
          </>
        ) : (
          <div className="ph">
            no preview
            {n ? (
              <button className="secondary" style={{ marginLeft: 8 }} disabled={busy} onClick={regen}>
                generate
              </button>
            ) : null}
          </div>
        )}
      </div>
      <div className="body">
        <span className="name">{exp.name}</span>
        <span className="meta">
          {exp.duration_s != null && <span>{formatSeconds(exp.duration_s)}</span>}
          <span>{n} fr</span>
          {exp.size_bytes != null && <span title="size on disk (all files in the run folder)">{exp.size_bytes >= 1e9 ? `${(exp.size_bytes / 1e9).toFixed(2)} GB` : `${(exp.size_bytes / 1e6).toFixed(0)} MB`}</span>}
          {exp.ir_format && <span>{exp.ir_format.replace("TemperatureLinear", "TL ")}</span>}
          {meta.material != null && <span>{String(meta.material)}</span>}
          {meta.rf_forward_power_w != null && <span>{String(meta.rf_forward_power_w)} W</span>}
        </span>
        <span>
          {exp.complete ? <span className="badge ok">complete</span> : <span className="badge bad">INCOMPLETE{dropped ? ` · ${dropped} dropped` : ""}</span>}
          <span className="badge lib" style={{ marginLeft: 6 }} title={onDrive ? "Stored on the external drive" : "Stored on local disk"}>{onDrive ? "Drive" : "Local"}</span>
          {roisDiffer && <span className="badge warn" style={{ marginLeft: 6 }} title="You've changed this run's ROIs since its exports were built. Open it and regenerate to update the ROI plot, video and roi_series.csv.">ROIs edited</span>}
        </span>
        <div className="actions">
          <button className="primary" disabled={!n || !!exp.error} onClick={onOpen}>
            open
          </button>
          <button className="secondary" disabled={busy} onClick={reveal} title="Show in Finder / Explorer">
            reveal
          </button>
          <button className="secondary" disabled={busy || !n || !!exp.error} onClick={exportH5} title="Export the whole recording to HDF5 (in the experiment's exports folder)">
            export
          </button>
          {onDrive ? (
            <button className="secondary" disabled={busy} onClick={() => moveTo("local")} title="Copy this run back to local disk (verified, then removed from the drive)">
              ← local
            </button>
          ) : (
            <button className="secondary" disabled={busy || !driveConnected} onClick={() => moveTo("drive")}
              title={driveConnected ? "Move this run to the external drive to free local space (copy → verify → delete)" : "Register an external drive in Setup → Storage first"}>
              → drive
            </button>
          )}
          <button className="danger" disabled={busy} onClick={remove} title="Delete this run and everything in its folder (no undo)" style={{ marginLeft: "auto" }}>
            delete
          </button>
        </div>
        {move && (
          <div style={{ marginTop: 4 }}>
            <div className="hint">{onDrive ? "bringing back to local" : "moving to drive"}… {move.total > 0 ? `${Math.round((move.done / move.total) * 100)}%` : ""}</div>
            <div className="progressbar" style={{ marginTop: 3 }}><div className={`progressbar-fill${move.total > 0 ? "" : " indeterminate"}`} style={move.total > 0 ? { width: `${Math.min(100, Math.round((move.done / move.total) * 100))}%` } : undefined} /></div>
          </div>
        )}
        {exp.error && <div className="errbox">{exp.error}</div>}
        {note && <div className={note.startsWith("HDF5 written") ? "hint" : "errbox"} style={{ wordBreak: "break-all" }}>{note}</div>}
      </div>
    </div>
  );
}
