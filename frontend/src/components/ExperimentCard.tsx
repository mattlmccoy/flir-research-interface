import { useState } from "react";
import { api, type Experiment } from "../lib/api.ts";
import { formatSeconds, keyframeBackgroundPosition, keyframeIndex } from "../lib/keyframes.ts";

interface Props { exp: Experiment; onOpen: () => void; onChanged: () => void; }

export function ExperimentCard({ exp, onOpen, onChanged }: Props) {
  const [k, setK] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const kf = exp.previews?.keyframes;
  const count = kf?.count ?? 0;
  const n = exp.n_frames ?? exp.frames_on_disk;
  const meta = exp.experiment ?? {};
  // content-addressed cache key: regenerated previews change the sha, so the URL changes
  const v = exp.previews ? `${exp.previews.preview.sha256.slice(0, 12)}` : "";
  const kv = exp.previews ? `${exp.previews.keyframes.sha256.slice(0, 12)}` : "";
  const dropped = (exp.manifest as { queue_dropped?: number } | null)?.queue_dropped ?? 0;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!count) return;
    const r = e.currentTarget.getBoundingClientRect();
    setK(keyframeIndex(e.clientX - r.left, r.width, count));
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
  async function regen(e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(true);
    setNote(null);
    try {
      await api.regeneratePreviews(exp.name);
      onChanged();
    } catch (err) {
      setNote(String(err));
    } finally {
      setBusy(false);
    }
  }

  const unitLabel = exp.previews?.units === "counts" ? " (raw counts)" : "";
  return (
    <div className="exp-card">
      <div className="thumb" onMouseMove={onMove} onMouseLeave={() => setK(null)} onClick={onOpen} title="open">
        {exp.previews ? (
          <>
            <img src={`${api.previewUrl(exp.name)}?v=${v}`} alt="" />
            {k !== null && kf && (
              <div
                className="kf"
                style={{ backgroundImage: `url(${api.keyframesUrl(exp.name)}?v=${kv})`, backgroundPosition: keyframeBackgroundPosition(k, count) }}
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
          {exp.ir_format && <span>{exp.ir_format.replace("TemperatureLinear", "TL ")}</span>}
          {meta.material != null && <span>{String(meta.material)}</span>}
          {meta.rf_forward_power_w != null && <span>{String(meta.rf_forward_power_w)} W</span>}
        </span>
        <span>{exp.complete ? <span className="badge ok">complete</span> : <span className="badge bad">INCOMPLETE{dropped ? ` · ${dropped} dropped` : ""}</span>}</span>
        <div className="actions">
          <button className="primary" disabled={!n} onClick={onOpen}>
            open
          </button>
          <button className="secondary" disabled={busy} onClick={reveal} title="Show in Finder / Explorer">
            reveal
          </button>
          <button className="secondary" disabled title="Milestone 7">
            export
          </button>
        </div>
        {note && <div className="errbox">{note}</div>}
      </div>
    </div>
  );
}
