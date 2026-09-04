import { useState } from "react";
import { NumberField } from "./NumberField.tsx";
import { api, type MediaJob } from "../lib/api.ts";

interface Props {
  name: string;
  nFrames: number;
  index: number; // current playhead, for "set in/out here"
  tS: number[]; // timeline seconds per frame
  onClose: () => void;
}

function fmtSecs(s: number): string { return `${s.toFixed(2)} s`; }
function fmtBytes(n: number): string { return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${(n / 1e3).toFixed(0)} kB`; }

/** Full-screen editor: pick a time window and overlays, then export an MP4 or GIF of the run. */
export function MediaExportEditor({ name, nFrames, index, tS, onClose }: Props) {
  const [start, setStart] = useState(0);
  const [stop, setStop] = useState(nFrames);
  const [fmt, setFmt] = useState<"mp4" | "gif">("mp4");
  const [scale, setScale] = useState(2);
  const [speed, setSpeed] = useState(1);
  const [rois, setRois] = useState(true);
  const [frameStats, setFrameStats] = useState(true);
  const [timestamp, setTimestamp] = useState(true);
  const [colorbar, setColorbar] = useState(true);
  const [title, setTitle] = useState("");
  const [job, setJob] = useState<MediaJob | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const busy = job?.state === "running";

  const clampWin = (a: number, b: number): [number, number] => {
    const s = Math.max(0, Math.min(a, nFrames - 1));
    const e = Math.max(s + 1, Math.min(b, nFrames));
    return [s, e];
  };
  const [s0, s1] = clampWin(start, stop);
  const windowSecs = tS.length ? (tS[Math.min(s1, tS.length) - 1] ?? 0) - (tS[s0] ?? 0) : 0;

  async function run() {
    setErr(null); setJob({ state: "running", step: "starting", done: 0, total: 0 });
    try {
      await api.exportMedia(name, {
        start: s0, stop: s1, scale, speed, fmt, with_rois: rois,
        frame_stats: frameStats, timestamp, colorbar, title: title.trim() || null,
      });
      for (;;) {
        await new Promise((r) => setTimeout(r, 700));
        const jb = await api.mediaStatus(name);
        setJob(jb);
        if (jb.state === "done" || jb.state === "error" || jb.state === "idle") break;
      }
    } catch (e) { setErr(String(e)); setJob(null); }
  }

  const pct = job && job.total ? Math.round((job.done! / job.total) * 100) : null;
  return (
    <div className="media-editor" role="dialog" aria-label="Media export">
      <div className="media-editor-head">
        <b>Media export</b>
        <span className="muted">{name}</span>
        <button className="secondary" style={{ marginLeft: "auto" }} onClick={onClose}>close</button>
      </div>
      <div className="media-editor-body">
        <div className="media-window">
          <div className="kv">
            <span>from frame</span>
            <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <NumberField min={0} max={nFrames - 1} value={s0} style={{ width: 90 }} aria-label="window start frame" onChange={(n) => setStart(n)} />
              <button className="secondary" onClick={() => setStart(index)} title="Set the start to the current frame">at playhead</button>
              <span className="hint">{tS[s0] != null ? fmtSecs(tS[s0]) : ""}</span>
            </span>
            <span>to frame</span>
            <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <NumberField min={1} max={nFrames} value={s1} style={{ width: 90 }} aria-label="window stop frame" onChange={(n) => setStop(n)} />
              <button className="secondary" onClick={() => setStop(index + 1)} title="Set the end to the current frame">at playhead</button>
              <span className="hint">{tS[Math.min(s1, tS.length) - 1] != null ? fmtSecs(tS[Math.min(s1, tS.length) - 1]) : ""}</span>
            </span>
            <span>window</span>
            <span className="v">{s1 - s0} frames · {fmtSecs(windowSecs)}</span>
          </div>
          <input type="range" min={0} max={nFrames - 1} value={s0} aria-label="drag window start" style={{ width: "100%", marginTop: 8 }} onChange={(e) => setStart(Number(e.target.value))} />
          <input type="range" min={1} max={nFrames} value={s1} aria-label="drag window end" style={{ width: "100%" }} onChange={(e) => setStop(Number(e.target.value))} />
        </div>

        <div className="media-opts kv">
          <span>format</span>
          <span className="v plain">
            <select value={fmt} onChange={(e) => setFmt(e.target.value as "mp4" | "gif")} aria-label="format">
              <option value="mp4">MP4 (H.264)</option><option value="gif">Animated GIF</option>
            </select>
          </span>
          <span>size</span>
          <span className="v plain">
            <select value={scale} onChange={(e) => setScale(Number(e.target.value))} aria-label="size">
              <option value={1}>1× (native)</option><option value={2}>2× (crisp)</option>
            </select>
          </span>
          <span>speed</span>
          <span className="v plain">
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="speed">
              {[0.5, 1, 2, 4, 8].map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </span>
        </div>

        <div className="media-title">
          <label className="hint">Title / caption <input type="text" value={title} maxLength={80} placeholder="(optional, baked into the frame)" style={{ width: "100%" }} onChange={(e) => setTitle(e.target.value)} /></label>
        </div>

        <div className="media-overlays">
          <b className="hint">Overlays</b>
          <label><input type="checkbox" checked={rois} onChange={(e) => setRois(e.target.checked)} /> ROIs + values</label>
          <label><input type="checkbox" checked={frameStats} onChange={(e) => setFrameStats(e.target.checked)} /> frame min/max/mean</label>
          <label><input type="checkbox" checked={timestamp} onChange={(e) => setTimestamp(e.target.checked)} /> timestamp</label>
          <label><input type="checkbox" checked={colorbar} onChange={(e) => setColorbar(e.target.checked)} /> colour bar</label>
        </div>

        <div className="media-actions">
          <button className="primary" disabled={busy || nFrames === 0} onClick={run}>
            {busy ? "rendering…" : `Export ${fmt.toUpperCase()}`}
          </button>
          {busy && (
            <div style={{ flex: 1 }}>
              <div className="hint">{job?.step === "encoding" ? `encoding · frame ${job.done}/${job.total}${pct != null ? ` (${pct}%)` : ""}` : job?.step}</div>
              <div className="progressbar"><div className="progressbar-fill" style={{ width: `${pct ?? 5}%` }} /></div>
            </div>
          )}
          {job?.state === "done" && job.file && (
            <span className="hint" style={{ color: "var(--accent)" }}>
              ✓ <a className="dl" href={api.clipUrl(name, job.file.name)} target="_blank" rel="noreferrer" download={job.file.name}>{job.file.name}</a> · {fmtBytes(job.file.bytes)}
              {job.file.note ? ` · ${job.file.note}` : ""}
            </span>
          )}
          {(err || job?.error) && <span className="errbox">{err ?? job?.error}</span>}
        </div>
      </div>
    </div>
  );
}
