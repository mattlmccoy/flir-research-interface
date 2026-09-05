import { useEffect, useRef, useState } from "react";
import { NumberField } from "./NumberField.tsx";
import { api, type MediaJob, type RangeJob } from "../lib/api.ts";

interface RoiPick { id: number; name?: string; kind?: string; color?: string }
interface Props {
  name: string;
  nFrames: number;
  index: number; // current playhead in playback, seeds the scrubber
  tS: number[]; // timeline seconds per frame
  rois: RoiPick[]; // stored ROIs, for the ROI picker
  hasVisible?: boolean; // the run has an aligned visible-camera recording
  onClose: () => void;
}

// Matches the backend overlay palette (annotate.DEFAULT_COLORS), so a picker dot shows the colour
// the ROI's box and plot line will actually have in the export.
const MEDIA_PALETTE = ["#ffb000", "#4cc9f0", "#ff8ad8", "#7cff6b", "#ff6b6b", "#c8a2ff", "#ffffff"];
function dotColor(r: RoiPick, i: number): string { return r.color ?? MEDIA_PALETTE[i % MEDIA_PALETTE.length]; }

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
export function MediaExportEditor({ name, nFrames, index, tS, rois, hasVisible, onClose }: Props) {
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
  const [palette, setPalette] = useState("inferno");
  const [visibleOpacity, setVisibleOpacity] = useState(0);
  const [title, setTitle] = useState("");
  const [job, setJob] = useState<MediaJob | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const busy = job?.state === "running";

  // The whole-run temperature scan (display range) is the slow part of a first preview — 30s+ on a
  // long run, more when the files are still cold. Run it once as a job with a REAL progress bar,
  // then gate the preview on it. range.json makes this a one-time cost per run.
  const [range, setRange] = useState<RangeJob | null>(null);
  const rangeReady = range?.state === "done";
  useEffect(() => {
    let alive = true;
    let timer = 0;
    setRange(null);
    (async () => {
      try {
        let st = await api.rangeStatus(name);
        if (st.state !== "done") st = await api.computeRange(name);
        if (alive) setRange(st);
        while (alive && st.state === "running") {
          await new Promise<void>((r) => { timer = window.setTimeout(() => r(), 400); });
          if (!alive) break;
          st = await api.rangeStatus(name);
          if (alive) setRange(st);
        }
      } catch (e) {
        if (alive) setRange({ state: "error", done: 0, total: 0, error: String(e) });
      }
    })();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [name]);

  // Debounced preview URL: recompose only after scrubbing/typing settles. Held until the range scan
  // finishes, so the image request never triggers its own blocking scan.
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewLoading, setPreviewLoading] = useState(true);
  useEffect(() => {
    if (!rangeReady) return;
    setPreviewLoading(true);
    const id = window.setTimeout(() => {
      setPreviewUrl(api.mediaPreviewUrl(name, scrub, { with_rois: showRois, frame_stats: frameStats, timestamp, colorbar, title: title.trim() || null, plot_series: plotSeries, overlay_rois: selIds, visible_opacity: visibleOpacity, palette, start, stop }));
    }, 120);
    return () => window.clearTimeout(id);
  }, [rangeReady, name, scrub, showRois, frameStats, timestamp, colorbar, title, plotSeries.join(","), selIds.join(","), visibleOpacity, palette, start, stop]);

  const windowSecs = tS.length ? (tS[Math.min(stop, tS.length) - 1] ?? 0) - (tS[start] ?? 0) : 0;

  async function run() {
    setErr(null); setJob({ state: "running", step: "starting", done: 0, total: 0 });
    try {
      await api.exportMedia(name, { start, stop, step, scale, speed, fmt, with_rois: showRois, frame_stats: frameStats, timestamp, colorbar, title: title.trim() || null, plot_series: plotSeries, overlay_rois: selIds, visible_opacity: visibleOpacity, palette });
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
          <div className="media-preview-frame">
            {rangeReady && previewUrl && <img src={previewUrl} alt="preview" style={{ opacity: previewLoading ? 0.25 : 1 }} onLoad={() => setPreviewLoading(false)} onError={() => setPreviewLoading(false)} />}
            {!rangeReady && (
              <div className="media-preview-overlay range-scan">
                {range?.state === "error" ? (
                  <span className="bad">temperature-range scan failed: {range.error}</span>
                ) : (() => {
                  const total = range?.total ?? 0;
                  const done = range?.done ?? 0;
                  const pct = total ? Math.round((done / total) * 100) : 0;
                  return (
                    <>
                      <div className="hint">Analyzing temperature range… {pct}%{total ? ` (${done.toLocaleString()} / ${total.toLocaleString()} frames)` : ""}</div>
                      <div className="progressbar"><div className="progressbar-fill" style={{ width: `${Math.max(3, pct)}%` }} /></div>
                      <div className="hint" style={{ opacity: 0.7 }}>one-time per run — reused on every later open</div>
                    </>
                  );
                })()}
              </div>
            )}
            {rangeReady && previewLoading && <div className="media-preview-overlay"><span className="spinner" /> rendering preview…</div>}
          </div>
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
          <span>palette</span><span className="v plain"><select value={palette} onChange={(e) => setPalette(e.target.value)} aria-label="colour palette">{["inferno", "iron", "magma", "plasma", "viridis", "turbo", "rainbow", "grayscale", "blackhot"].map((p) => <option key={p} value={p}>{p}</option>)}</select></span>
          {hasVisible && <span title="Blend the recorded visible camera over the thermal image">visible cam</span>}
          {hasVisible && (
            <span className="v plain" style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
              <input type="range" min={0} max={1} step={0.05} value={visibleOpacity} style={{ width: 130 }} aria-label="visible camera opacity" onChange={(e) => setVisibleOpacity(Number(e.target.value))} />
              <span style={{ minWidth: 34, textAlign: "right" }}>{visibleOpacity === 0 ? "off" : `${Math.round(visibleOpacity * 100)}%`}</span>
            </span>
          )}
          <span>speed</span><span className="v plain"><select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="speed">{[0.5, 1, 2, 4, 8].map((s) => <option key={s} value={s}>{s}×</option>)}</select></span>
          <span title="Keep every Nth frame — fewer frames = smaller/faster file (handy for GIFs)">keep every</span>
          <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <NumberField min={1} max={100} value={step} style={{ width: 64 }} aria-label="keep every Nth frame" onChange={(f) => setStep(Math.max(1, Math.floor(f)))} />
            <span className="hint">frame{step === 1 ? "" : "s"} → {Math.ceil((stop - start) / step)} out{fmt === "gif" ? ` @ ${Math.min(20, (30 * speed) / step).toFixed(0)} fps` : ""}</span>
          </span>
          <span title="Tick a ROI to draw it on the frame and plot it below. For an area ROI, tick any of mean/min/max as separate lines.">ROIs</span>
          <div className="v plain roi-rows">
            {rois.length === 0 && <span className="hint">no ROIs on this run</span>}
            {rois.map((r, i) => {
              const on = r.id in sel;
              const spot = r.kind === "spot";
              return (
                <div key={r.id} className={`roi-row${on ? " on" : ""}`}>
                  <label className="roi-name">
                    <input type="checkbox" checked={on} onChange={() => toggleRoi(r.id)} />
                    <span className="roi-dot" style={{ background: dotColor(r, i) }} />
                    {r.name ?? `ROI ${r.id}`}
                  </label>
                  {on && !spot && (
                    <span className="roi-stats">
                      {["mean", "min", "max"].map((s) => (
                        <label key={s}><input type="checkbox" checked={(sel[r.id] ?? []).includes(s)} onChange={() => toggleStat(r.id, s)} /> {s}</label>
                      ))}
                    </span>
                  )}
                </div>
              );
            })}
            {selIds.length > 0 && <span className="hint">Only these {selIds.length} ROI{selIds.length === 1 ? "" : "s"} are drawn on the export.</span>}
          </div>
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
