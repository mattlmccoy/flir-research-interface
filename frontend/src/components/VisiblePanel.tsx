import React, { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../lib/api.ts";
import { streamMjpeg } from "../lib/mjpeg.ts";
import { DEFAULT_OVERLAY, VISIBLE_MODES, type LayoutAction, type Overlay, type VisibleMode } from "../lib/layout.ts";

/** Live MJPEG view: fetches the stream itself so unmounting aborts it (the operator's transcode ends at once).
 *  `plain` renders only the image (for the overlay). */
export function VisibleLive({ big = false, plain = false, topLayer }: { big?: boolean; plain?: boolean; topLayer?: ReactNode }) {
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
  if (plain) return <img ref={img} alt="visible camera overlay" className="fill" />;
  return (
    <div className={`visible-box ${big ? "big" : ""}`} ref={boxRef}>
      <img ref={img} alt="visible camera" />
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

interface VideoProps { name: string; t: number; playing: boolean; speed: number; measuredFps?: number | null; big?: boolean; plain?: boolean; topLayer?: ReactNode; }

/** Recorded visible.mp4 kept in step with the thermal cursor (host-clock alignment, not frame-exact). */
export function VisibleVideo({ name, t, playing, speed, measuredFps, big = false, plain = false, topLayer }: VideoProps) {
  const video = useRef<HTMLVideoElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const layerBox = useMediaBox(boxRef, video);
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.playbackRate = Number.isFinite(speed) ? Math.min(4, Math.max(0.25, speed)) : 4;
    if (playing) {
      if (Math.abs(v.currentTime - t) > 0.3) v.currentTime = t;
      if (v.paused) v.play().catch(() => undefined);
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - t) > 0.02) v.currentTime = t;
    }
  }, [t, playing, speed]);
  if (plain) return <video ref={video} src={api.visibleVideoUrl(name)} muted playsInline preload="auto" className="fill" />;
  return (
    <div className={`visible-box ${big ? "big" : ""}`} ref={boxRef}>
      <video ref={video} src={api.visibleVideoUrl(name)} muted playsInline preload="auto" />
      <span className="tag">recorded visible{measuredFps ? ` · ${measuredFps.toFixed(1)} fps` : ""} · host-clock aligned</span>
      {topLayer && layerBox && <div className="top-layer" style={layerBox}>{topLayer}</div>}
    </div>
  );
}

interface Placement { visibleMode: VisibleMode; overlay: Overlay; dispatch: (a: LayoutAction) => void; aligned?: boolean; }
type PanelProps = Placement & (
  | { mode: "live"; available: boolean; reason?: string }
  | { mode: "playback"; name: string; hasVideo: boolean; t: number; playing: boolean; speed: number; measuredFps?: number | null });

function Slider({ label, value, min, max, step, unit, onChange }: { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <label style={{ display: "contents" }}>
      <span>{label}</span>
      <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: 110 }} aria-label={label} />
        <span style={{ minWidth: 44, textAlign: "right" }}>{value.toFixed(step < 1 ? 2 : 0)}{unit ?? ""}</span>
      </span>
    </label>
  );
}

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
    if (!p.available) return <div className="hint">Visible camera preview unavailable: {p.reason ?? "ffmpeg or RTSP credentials not configured"}.</div>;
    return (
      <>
        {placement}
        {registration}
        {mode === "rail" && (
          <div className="row">
            <button className={on ? "danger" : "secondary"} onClick={() => setOn(!on)}>{on ? "stop preview" : "show visible camera"}</button>
          </div>
        )}
        <div className="hint">RTSP /avc/ch1 → MJPEG 640 px; the camera limits it to ~8 fps while the thermal stream runs, about a second of encoder delay.</div>
        {mode === "rail" && on && <VisibleLive />}
      </>
    );
  }
  if (!p.hasVideo) return <div className="hint">This recording has no visible video.</div>;
  return (
    <>
      {placement}
      {registration}
      {mode === "rail" && <VisibleVideo name={p.name} t={p.t} playing={p.playing} speed={p.speed} measuredFps={p.measuredFps} />}
    </>
  );
}
