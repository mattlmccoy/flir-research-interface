import { useEffect, useRef, useState } from "react";
import { NumberField } from "./NumberField.tsx";
import { api, type MediaJob } from "../lib/api.ts";

interface Props {
  name: string;
  nFrames: number;
  index: number; // current playhead in playback, seeds the scrubber
  tS: number[]; // timeline seconds per frame
  rois: { id: number; name?: string; kind?: string }[]; // stored ROIs, for the live-plot picker
  onClose: () => void;
}

function fmtSecs(s: number): string { return `${s.toFixed(2)} s`; }
function fmtBytes(n: number): string { return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${(n / 1e3).toFixed(0)} kB`; }

/** A video-style crop bar: draggable in/out handles plus a scrub playhead over the whole run. */
function TrimBar({ n, start, stop, scrub, onStart, onStop, onScrub }: {
  n: number; start: number; stop: number; scrub: number;
  onStart: (f: number) => void; onStop: (f: number) => void; onScrub: (f: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const frameAt = (clientX: number): number => {
    const el = ref.current; if (!el) return 0;
    const r = el.getBoundingClientRect();
    return Math.round(((clientX - r.left) / r.width) * (n - 1));
  };
  const drag = (kind: "start" | "stop" | "scrub") => (e: React.PointerEvent) => {
    e.preventDefault(); (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    const move = (ev: PointerEvent) => {
      const f = Math.max(0, Math.min(n - 1, frameAt(ev.clientX)));
      if (kind === "start") onStart(Math.min(f, stop - 1));
      else if (kind === "stop") onStop(Math.max(f + 1, start + 1));
      else onScrub(f);
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    move(e.nativeEvent);
  };
  const pct = (f: number) => `${(f / Math.max(1, n - 1)) * 100}%`;
  return (
    <div className="trimbar" ref={ref} onPointerDown={drag("scrub")}>
      <div className="trim-sel" style={{ left: pct(start), right: `calc(100% - ${pct(stop - 1)})` }} />
      <div className="trim-handle in" style={{ left: pct(start) }} onPointerDown={(e) => { e.stopPropagation(); drag("start")(e); }} title="Start" />
      <div className="trim-handle out" style={{ left: pct(stop - 1) }} onPointerDown={(e) => { e.stopPropagation(); drag("stop")(e); }} title="End" />
      <div className="trim-playhead" style={{ left: pct(scrub) }} />
    </div>
  );
}

/** Full-screen editor: scrub a live preview and set an in/out window, then export MP4 or GIF. */
export function MediaExportEditor({ name, nFrames, index, tS, rois, onClose }: Props) {
  const [start, setStart] = useState(0);
  const [stop, setStop] = useState(nFrames);
  const [scrub, setScrub] = useState(Math.min(index, nFrames - 1));
  const [fmt, setFmt] = useState<"mp4" | "gif">("mp4");
  const [scale, setScale] = useState(2);
  const [speed, setSpeed] = useState(1);
  const [step, setStep] = useState(1);
  // Per-ROI selection: id -> stats to plot. Presence = the ROI's box is drawn on the frame; the
  // stat list is the lines plotted for it (spots use "value"; an empty list = box only, no line).
  const [sel, setSel] = useState<Record<number, string[]>>({});
  const isSpot = (id: number) => rois.find((r) => r.id === id)?.kind === "spot";
  const toggleRoi = (id: number) => setSel((cur) => {
    const next = { ...cur };
    if (id in next) delete next[id];
    else next[id] = isSpot(id) ? ["value"] : ["mean"];
    return next;
  });
  const toggleStat = (id: number, s: string) => setSel((cur) => {
    const stats = cur[id] ?? [];
    return { ...cur, [id]: stats.includes(s) ? stats.filter((x) => x !== s) : [...stats, s] };
  });
  const selIds = Object.keys(sel).map(Number);
  const plotSeries = selIds.flatMap((id) => (sel[id] ?? []).map((s) => `${id}:${s}`));
  const [showRois, setShowRois] = useState(true);
  const [frameStats, setFrameStats] = useState(true);
  const [timestamp, setTimestamp] = useState(true);
  const [colorbar, setColorbar] = useState(true);
  const [title, setTitle] = useState("");
  const [job, setJob] = useState<MediaJob | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const busy = job?.state === "running";

  // Debounced preview URL: recompose only after scrubbing/typing settles.
  const [previewUrl, setPreviewUrl] = useState("");
  useEffect(() => {
    const id = window.setTimeout(() => {
      setPreviewUrl(api.mediaPreviewUrl(name, scrub, { with_rois: showRois, frame_stats: frameStats, timestamp, colorbar, title: title.trim() || null, plot_series: plotSeries, overlay_rois: selIds, start, stop }));
    }, 120);
    return () => window.clearTimeout(id);
  }, [name, scrub, showRois, frameStats, timestamp, colorbar, title, plotSeries.join(","), selIds.join(","), start, stop]);

  const windowSecs = tS.length ? (tS[Math.min(stop, tS.length) - 1] ?? 0) - (tS[start] ?? 0) : 0;

  async function run() {
    setErr(null); setJob({ state: "running", step: "starting", done: 0, total: 0 });
    try {
      await api.exportMedia(name, { start, stop, step, scale, speed, fmt, with_rois: showRois, frame_stats: frameStats, timestamp, colorbar, title: title.trim() || null, plot_series: plotSeries, overlay_rois: selIds });
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
        <b>Media export</b><span className="muted">{name}</span>
        <button className="secondary" style={{ marginLeft: "auto" }} onClick={onClose}>close</button>
      </div>
      <div className="media-editor-body">
        <div className="media-preview">
          {previewUrl ? <img src={previewUrl} alt="preview" /> : <div className="muted">loading preview…</div>}
          <div className="hint" style={{ textAlign: "center" }}>frame {scrub} · {tS[scrub] != null ? fmtSecs(tS[scrub]) : ""}</div>
        </div>

        <TrimBar n={nFrames} start={start} stop={stop} scrub={scrub}
          onStart={(f) => { setStart(f); setScrub(f); }} onStop={(f) => { setStop(f); setScrub(f - 1); }} onScrub={setScrub} />
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 6 }}>
          <span className="hint" style={{ display: "flex", gap: 6, alignItems: "center" }}>in
            <NumberField min={0} max={nFrames - 1} value={start} style={{ width: 80 }} aria-label="window start frame" onChange={(f) => { setStart(Math.min(f, stop - 1)); setScrub(Math.min(f, stop - 1)); }} />
            <button className="secondary" onClick={() => { setStart(scrub); }} title="Set start to the preview frame">set here</button>
          </span>
          <span className="v">{stop - start} frames · {fmtSecs(windowSecs)}</span>
          <span className="hint" style={{ display: "flex", gap: 6, alignItems: "center" }}>out
            <NumberField min={1} max={nFrames} value={stop} style={{ width: 80 }} aria-label="window stop frame" onChange={(f) => { setStop(Math.max(f, start + 1)); setScrub(Math.max(f, start + 1) - 1); }} />
            <button className="secondary" onClick={() => { setStop(scrub + 1); }} title="Set end to the preview frame">set here</button>
          </span>
        </div>

        <div className="media-opts kv">
          <span>format</span><span className="v plain"><select value={fmt} onChange={(e) => setFmt(e.target.value as "mp4" | "gif")} aria-label="format"><option value="mp4">MP4 (H.264)</option><option value="gif">Animated GIF</option></select></span>
          <span>size</span><span className="v plain"><select value={scale} onChange={(e) => setScale(Number(e.target.value))} aria-label="size"><option value={1}>1× (native)</option><option value={2}>2× (crisp)</option></select></span>
          <span>speed</span><span className="v plain"><select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="speed">{[0.5, 1, 2, 4, 8].map((s) => <option key={s} value={s}>{s}×</option>)}</select></span>
          <span title="Keep every Nth frame — fewer frames = smaller/faster file (handy for GIFs)">keep every</span>
          <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <NumberField min={1} max={100} value={step} style={{ width: 64 }} aria-label="keep every Nth frame" onChange={(f) => setStep(Math.max(1, Math.floor(f)))} />
            <span className="hint">frame{step === 1 ? "" : "s"} → {Math.ceil((stop - start) / step)} out{fmt === "gif" ? ` @ ${Math.min(20, (30 * speed) / step).toFixed(0)} fps` : ""}</span>
          </span>
          <span title="Pick ROIs to focus: each is drawn on the frame and plotted below. For an area ROI, pick any of mean/min/max as separate lines.">ROIs</span>
          <span className="v plain roi-picker">
            {rois.length === 0 && <span className="hint">no ROIs on this run</span>}
            {rois.map((r) => {
              const on = r.id in sel;
              const spot = r.kind === "spot";
              return (
                <span key={r.id} className={`roi-group${on ? " on" : ""}`}>
                  <button type="button" className={`chip${on ? " on" : ""}`} aria-pressed={on}
                    onClick={() => toggleRoi(r.id)}>{r.name ?? `ROI ${r.id}`}</button>
                  {on && !spot && ["mean", "min", "max"].map((s) => (
                    <button key={s} type="button" className={`chip stat${(sel[r.id] ?? []).includes(s) ? " on" : ""}`}
                      aria-pressed={(sel[r.id] ?? []).includes(s)} onClick={() => toggleStat(r.id, s)}>{s}</button>
                  ))}
                </span>
              );
            })}
          </span>
          {selIds.length > 0 && <span /> }
          {selIds.length > 0 && <span className="hint">Only these {selIds.length} ROI{selIds.length === 1 ? "" : "s"} are drawn on the export.</span>}
        </div>
        <label className="hint">Title / caption <input type="text" value={title} maxLength={80} placeholder="(optional, baked into the frame)" style={{ width: "100%" }} onChange={(e) => setTitle(e.target.value)} /></label>
        <div className="media-overlays">
          <b className="hint">Overlays</b>
          <label><input type="checkbox" checked={showRois} onChange={(e) => setShowRois(e.target.checked)} /> ROIs + values</label>
          <label><input type="checkbox" checked={frameStats} onChange={(e) => setFrameStats(e.target.checked)} /> frame min/max/mean</label>
          <label><input type="checkbox" checked={timestamp} onChange={(e) => setTimestamp(e.target.checked)} /> timestamp</label>
          <label><input type="checkbox" checked={colorbar} onChange={(e) => setColorbar(e.target.checked)} /> colour bar</label>
        </div>

        <div className="media-actions">
          <button className="primary" disabled={busy || nFrames === 0} onClick={run}>{busy ? "rendering…" : `Export ${fmt.toUpperCase()}`}</button>
          {busy && (
            <div style={{ flex: 1 }}>
              <div className="hint">{job?.step === "encoding" ? `encoding · frame ${job.done}/${job.total}${pct != null ? ` (${pct}%)` : ""}` : job?.step}</div>
              <div className="progressbar"><div className="progressbar-fill" style={{ width: `${pct ?? 5}%` }} /></div>
            </div>
          )}
          {job?.state === "done" && job.file && (
            <span className="hint" style={{ color: "var(--accent)" }}>✓ <a className="dl" href={api.clipUrl(name, job.file.name)} target="_blank" rel="noreferrer" download={job.file.name}>{job.file.name}</a> · {fmtBytes(job.file.bytes)}{job.file.note ? ` · ${job.file.note}` : ""}</span>
          )}
          {(err || job?.error) && <span className="errbox">{err ?? job?.error}</span>}
        </div>
      </div>
    </div>
  );
}
