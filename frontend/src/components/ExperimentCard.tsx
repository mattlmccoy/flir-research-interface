import { useState } from "react";
import { api, type Experiment, type Previews } from "../lib/api.ts";
import { formatSeconds, keyframeBackgroundPosition, keyframeIndex } from "../lib/keyframes.ts";
import { roisDifferFromStored, type Roi } from "../lib/roi.ts";

interface Props { exp: Experiment; onOpen: () => void; onChanged: () => void; currentRois?: Roi[]; }

export function ExperimentCard({ exp, onOpen, onChanged, currentRois = [] }: Props) {
  // Flag runs whose stored ROIs differ from the ones currently loaded in the tool, so the user
  // knows the run's derived files would change if regenerated. Only meaningful when the tool
  // actually has a ROI layout loaded.
  const roisDiffer = currentRois.length > 0 && roisDifferFromStored(currentRois, exp.rois ?? null);
  const [k, setK] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
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
          {roisDiffer && <span className="badge warn" style={{ marginLeft: 6 }} title="The ROIs loaded in the tool differ from the ones stored with this run. Open it to review the ROIs; its derived files (ROI plot, video, roi_series.csv) would change if you regenerate.">ROIs differ</span>}
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
          <button className="danger" disabled={busy} onClick={remove} title="Delete this run and everything in its folder (no undo)" style={{ marginLeft: "auto" }}>
            delete
          </button>
        </div>
        {exp.error && <div className="errbox">{exp.error}</div>}
        {note && <div className={note.startsWith("HDF5 written") ? "hint" : "errbox"} style={{ wordBreak: "break-all" }}>{note}</div>}
      </div>
    </div>
  );
}
