import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.ts";
import { streamMjpeg } from "../lib/mjpeg.ts";

/** Live MJPEG view: fetches the stream itself so unmounting aborts it (the operator's transcode ends at once). */
export function VisibleLive({ big = false }: { big?: boolean }) {
  const img = useRef<HTMLImageElement>(null);
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
  return (
    <div className={`visible-box ${big ? "big" : ""}`}>
      <img ref={img} alt="visible camera" />
      <span className="tag">visible · {fps ? `${fps.toFixed(1)} fps` : "connecting…"} · ~1 s behind thermal</span>
      {err && <div className="errbox">{err}</div>}
    </div>
  );
}

interface VideoProps { name: string; t: number; playing: boolean; speed: number; measuredFps?: number | null; big?: boolean; }

/** Recorded visible.mp4 kept in step with the thermal cursor (host-clock alignment, not frame-exact). */
export function VisibleVideo({ name, t, playing, speed, measuredFps, big = false }: VideoProps) {
  const video = useRef<HTMLVideoElement>(null);
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
  return (
    <div className={`visible-box ${big ? "big" : ""}`}>
      <video ref={video} src={api.visibleVideoUrl(name)} muted playsInline preload="auto" />
      <span className="tag">recorded visible{measuredFps ? ` · ${measuredFps.toFixed(1)} fps` : ""} · host-clock aligned</span>
    </div>
  );
}

type PanelProps =
  | { mode: "live"; available: boolean; reason?: string; side: boolean; onSide: () => void }
  | { mode: "playback"; name: string; hasVideo: boolean; t: number; playing: boolean; speed: number; measuredFps?: number | null; side: boolean; onSide: () => void };

/** Rail section body: placement toggle plus the small in-rail view when not side by side. */
export function VisiblePanel(p: PanelProps) {
  const [on, setOn] = useState(false);
  const sideToggle = (
    <label className="hint" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <input type="checkbox" checked={p.side} onChange={p.onSide} /> side by side with the thermal image
    </label>
  );
  if (p.mode === "live") {
    if (!p.available) return <div className="hint">Visible camera preview unavailable: {p.reason ?? "ffmpeg or RTSP credentials not configured"}.</div>;
    return (
      <>
        <div className="row">
          {!p.side && <button className={on ? "danger" : "secondary"} onClick={() => setOn(!on)}>{on ? "stop preview" : "show visible camera"}</button>}
          {sideToggle}
        </div>
        <div className="hint">RTSP /avc/ch1 → MJPEG 640 px; the camera limits it to ~8 fps while the thermal stream runs, about a second of encoder delay.</div>
        {!p.side && on && <VisibleLive />}
      </>
    );
  }
  if (!p.hasVideo) return <div className="hint">This recording has no visible video.</div>;
  return (
    <>
      <div className="row">{sideToggle}</div>
      {!p.side && <VisibleVideo name={p.name} t={p.t} playing={p.playing} speed={p.speed} measuredFps={p.measuredFps} />}
    </>
  );
}
