import React, { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api.ts";
import { streamMjpeg } from "../lib/mjpeg.ts";
import { DEFAULT_OVERLAY, VISIBLE_MODES, type LayoutAction, type Overlay, type VisibleMode } from "../lib/layout.ts";
import { visibleSegmentAt, type VisibleInfo } from "../lib/visibleSegments.ts";
import { NEUTRAL_ADJUST, isNeutral, type VisibleAdjust } from "../lib/visibleAdjust.ts";
import { RAW_RANGE_NOTE, sourceNote } from "../lib/visibleAdjustUi.ts";
import { Slider, VisibleAdjustControls, adjustFilter, type RunAdjust } from "./VisibleAdjustControls.tsx";

/** Live MJPEG view: fetches the stream itself so unmounting aborts it (the operator's transcode ends at once).
 *  `plain` renders only the image (for the overlay). */
export function VisibleLive({ big = false, plain = false, topLayer, flipH = false, flipV = false, adjust }: { big?: boolean; plain?: boolean; topLayer?: ReactNode; flipH?: boolean; flipV?: boolean; adjust?: VisibleAdjust }) {
  const f = adjustFilter(adjust);
  const flip = { ...(flipH || flipV ? { transform: `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})` } : {}), ...f.style };
  const img = useRef<HTMLImageElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const layerBox = useMediaBox(boxRef, img);
  const [err, setErr] = useState<string | null>(null);
  const [fps, setFps] = useState<number | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let n = 0;
    let t0 = performance.now();
    const stop = streamMjpeg(api.visibleLiveUrl(), (jpeg) => {
      const el = img.current;
      if (!el) return;
      if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(jpeg);
      el.src = url;
      n += 1;
      const dt = performance.now() - t0;
      if (dt >= 2000) { setFps((n * 1000) / dt); n = 0; t0 = performance.now(); }
    }, (e) => { if (e) setErr(e); });
    return () => { stop(); if (url) URL.revokeObjectURL(url); };
  }, []);
  if (plain) return <>{f.svg}<img ref={img} alt="visible camera overlay" className="fill" style={flip} /></>;
  return (
    <div className={`visible-box ${big ? "big" : ""}`} ref={boxRef}>
      {f.svg}
      <img ref={img} alt="visible camera" style={flip} />
      <span className="tag">visible · {fps ? `${fps.toFixed(1)} fps` : "connecting…"} · ~1 s behind thermal</span>
      {topLayer && layerBox && <div className="top-layer" style={layerBox}>{topLayer}</div>}
      {err && <div className="errbox">{err}</div>}
    </div>
  );
}

/** Where the media element sits inside its box (contain-fitted media leaves letterbox bands). */
function useMediaBox(box: React.RefObject<HTMLElement | null>, media: React.RefObject<HTMLElement | null>) {
  const [b, setB] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  useEffect(() => {
    const host = box.current, el = media.current;
    if (!host || !el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const h = host.getBoundingClientRect(), m = el.getBoundingClientRect();
      setB({ left: m.left - h.left, top: m.top - h.top, width: m.width, height: m.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(host); ro.observe(el);
    return () => ro.disconnect();
  }, [box, media]);
  return b;
}

/** `rangeNote`: shown as a tag on the video when its range is not confirmed full (rangeNote()). */
interface VideoProps { name: string; t: number; playing: boolean; speed: number; vis?: VisibleInfo | null; measuredFps?: number | null; big?: boolean; plain?: boolean; topLayer?: ReactNode; flipH?: boolean; flipV?: boolean; adjust?: VisibleAdjust; rangeNote?: string | null; }

/** Recorded visible video kept in step with the thermal cursor (host-clock alignment, not frame-exact).
 *  A stream loss splits the recording into segments (visible.mp4, visible_001.mp4, …); the cursor
 *  picks the segment and time inside a gap shows nothing. */
export function VisibleVideo({ name, t, playing, speed, vis, measuredFps, big = false, plain = false, topLayer, flipH = false, flipV = false, adjust, rangeNote }: VideoProps) {
  const f = adjustFilter(adjust);
  const flip = { ...(flipH || flipV ? { transform: `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})` } : {}), ...f.style };
  const video = useRef<HTMLVideoElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const layerBox = useMediaBox(boxRef, video);
  const seg = visibleSegmentAt(vis ?? {}, t);
  const lastIndex = useRef(0);
  if (seg) lastIndex.current = seg.index;
  const index = lastIndex.current;
  const local = seg?.local ?? null;
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.playbackRate = Number.isFinite(speed) ? Math.min(4, Math.max(0.25, speed)) : 4;
    if (local === null) { if (!v.paused) v.pause(); return; } // stream gap
    if (playing) {
      if (Math.abs(v.currentTime - local) > 0.3) v.currentTime = local;
      if (v.paused) v.play().catch(() => undefined);
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - local) > 0.02) v.currentTime = local;
    }
  }, [local, index, playing, speed]);
  const src = index === 0 ? api.visibleVideoUrl(name) : api.visibleSegmentUrl(name, index);
  const hidden = local === null ? { ...flip, visibility: "hidden" as const } : flip;
  if (plain) return <>{f.svg}<video key={index} ref={video} src={src} muted playsInline preload="auto" className="fill" style={hidden} /></>;
  const nSeg = vis?.segments?.length ?? 1;
  return (
    <div className={`visible-box ${big ? "big" : ""}`} ref={boxRef}>
      {f.svg}
      <video key={index} ref={video} src={src} muted playsInline preload="auto" style={hidden} />
      <span className="tag">{local === null ? "visible stream lost here (gap)" : `recorded visible${nSeg > 1 ? ` · segment ${index + 1}/${nSeg}` : ""}${measuredFps ? ` · ${measuredFps.toFixed(1)} fps` : ""} · host-clock aligned`}</span>
      {rangeNote && <span className="range-tag" role="status">{rangeNote}</span>}
      {topLayer && layerBox && <div className="top-layer" style={layerBox}>{topLayer}</div>}
    </div>
  );
}

interface Placement { visibleMode: VisibleMode; overlay: Overlay; dispatch: (a: LayoutAction) => void; aligned?: boolean;
  /** The preset picker, shown first (presets also hold display and camera settings, so it shows without a visible camera too). */
  picker?: ReactNode; }
type PanelProps = Placement & (
  /** `adjust`: the live adjustment (layout); slider moves dispatch `setVisibleAdjust`. */
  | { mode: "live"; available: boolean; reason?: string; adjust: VisibleAdjust }
  /** `adjust`: the run's adjustment (useRunVisibleAdjust); `rangeNote`: warning when the shown video is not range-corrected. */
  | { mode: "playback"; name: string; hasVideo: boolean; t: number; playing: boolean; speed: number; vis?: VisibleInfo | null; measuredFps?: number | null; adjust: RunAdjust; rangeNote?: string | null });

/** Rail section body: placement (rail / side by side / overlay), overlay registration sliders, in-rail view. */
export function VisiblePanel(p: PanelProps) {
  const [on, setOn] = useState(false);
  const mode = p.visibleMode;
  const placement = (
    <div className="row" role="radiogroup" aria-label="visible camera placement">
      {VISIBLE_MODES.map((m) => (
        <label key={m} className="hint" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <input type="radio" name="visible-mode" checked={mode === m} onChange={() => p.dispatch({ type: "setVisibleMode", mode: m })} />
          {m === "rail" ? "in the rail" : m === "side" ? "side by side" : "overlay on IR"}
        </label>
      ))}
    </div>
  );
  const registration = mode === "overlay" && (p.aligned ? (
    <div className="kv">
      <Slider label="opacity" value={p.overlay.opacity} min={0} max={1} step={0.05} onChange={(v) => p.dispatch({ type: "setOverlay", patch: { opacity: v } })} />
    </div>
  ) : (
    <>
      <div className="kv">
        <Slider label="opacity" value={p.overlay.opacity} min={0} max={1} step={0.05} onChange={(v) => p.dispatch({ type: "setOverlay", patch: { opacity: v } })} />
        <Slider label="scale" value={p.overlay.scale} min={0.5} max={2} step={0.01} unit="×" onChange={(v) => p.dispatch({ type: "setOverlay", patch: { scale: v } })} />
        <Slider label="shift x" value={p.overlay.dx} min={-50} max={50} step={0.5} unit="%" onChange={(v) => p.dispatch({ type: "setOverlay", patch: { dx: v } })} />
        <Slider label="shift y" value={p.overlay.dy} min={-50} max={50} step={0.5} unit="%" onChange={(v) => p.dispatch({ type: "setOverlay", patch: { dy: v } })} />
      </div>
      <div className="row">
        <button className="secondary" onClick={() => p.dispatch({ type: "setOverlay", patch: DEFAULT_OVERLAY })}>reset alignment</button>
        <span className="hint">Rough manual placement. For a true fit use "align cameras…" below.</span>
      </div>
    </>
  ));
  if (p.mode === "live") {
    if (!p.available) return <>{p.picker}<div className="hint">Visible camera preview unavailable: {p.reason ?? "ffmpeg or RTSP credentials not configured"}.</div></>;
    return (
      <>
        {p.picker}
        {placement}
        {registration}
        <VisibleAdjustControls value={p.adjust} onChange={(adjust) => p.dispatch({ type: "setVisibleAdjust", adjust })}
          onReset={() => p.dispatch({ type: "setVisibleAdjust", adjust: NEUTRAL_ADJUST })} resetLabel="reset adjustment" resetDisabled={isNeutral(p.adjust)}
          notes={<span className="hint">display only · stamped into the next recording</span>} />
        {mode === "rail" && (
          <div className="row">
            <button className={on ? "danger" : "secondary"} onClick={() => setOn(!on)}>{on ? "stop preview" : "show visible camera"}</button>
          </div>
        )}
        <div className="hint">RTSP /avc/ch1 → MJPEG 640 px; the camera limits it to ~8 fps while the thermal stream runs, about a second of encoder delay.</div>
        {mode === "rail" && on && <VisibleLive adjust={p.adjust} />}
      </>
    );
  }
  if (!p.hasVideo) return <>{p.picker}<div className="hint">This recording has no visible video.</div></>;
  return (
    <>
      {p.picker}
      {placement}
      {registration}
      <VisibleAdjustControls value={p.adjust.adjust} onChange={p.adjust.set} onReset={p.adjust.reset} resetLabel="reset to as-recorded"
        resetDisabled={p.adjust.source !== "sidecar"}
        notes={<span className="hint">{p.adjust.save.state === "saving" ? "saving…" : p.adjust.save.state === "error" ? <span style={{ color: "var(--err)" }}>not saved: {p.adjust.save.error}</span> : sourceNote(p.adjust.source)}</span>} />
      {p.rangeNote && <div className="warnbox">{p.rangeNote}: near-white detail above level 235 {p.rangeNote === RAW_RANGE_NOTE ? "shows" : "may show"} as white.</div>}
      {mode === "rail" && <VisibleVideo name={p.name} t={p.t} playing={p.playing} speed={p.speed} vis={p.vis} measuredFps={p.measuredFps} adjust={p.adjust.adjust} rangeNote={p.rangeNote} />}
    </>
  );
}
