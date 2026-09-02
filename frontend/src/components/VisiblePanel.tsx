import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.ts";
import { streamMjpeg } from "../lib/mjpeg.ts";

type Props =
  | { mode: "live"; available: boolean; reason?: string }
  | { mode: "playback"; name: string; hasVideo: boolean; t: number; playing: boolean; speed: number; measuredFps?: number | null };

/**
 * Visible camera (Milestone 9 view). Live: a low-rate MJPEG relay, off by default because each
 * viewer costs one ffmpeg on the operator. Playback: the recorded visible.mp4, kept in step with
 * the thermal cursor (host-clock alignment, ~tens of ms; not frame-exact).
 */
export function VisiblePanel(p: Props) {
  const [on, setOn] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fps, setFps] = useState<number | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const img = useRef<HTMLImageElement>(null);

  // Live: fetch the MJPEG stream ourselves so stopping (or unmounting) aborts the request at once,
  // which ends the operator's transcode; an <img src> would keep the connection open on its own.
  useEffect(() => {
    if (p.mode !== "live" || !on) return;
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
    return () => { stop(); if (url) URL.revokeObjectURL(url); setFps(null); };
  }, [p.mode, on]);

  useEffect(() => {
    if (p.mode !== "playback") return;
    const v = video.current;
    if (!v || !p.hasVideo) return;
    v.playbackRate = Number.isFinite(p.speed) ? Math.min(4, Math.max(0.25, p.speed)) : 4;
    if (p.playing) {
      if (Math.abs(v.currentTime - p.t) > 0.3) v.currentTime = p.t;
      if (v.paused) v.play().catch(() => undefined);
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - p.t) > 0.02) v.currentTime = p.t;
    }
  }, [p]);

  if (p.mode === "live") {
    if (!p.available) return <div className="hint">Visible camera preview unavailable: {p.reason ?? "ffmpeg or RTSP credentials not configured"}.</div>;
    return (
      <>
        <div className="row">
          <button className={on ? "danger" : "secondary"} onClick={() => { setOn(!on); setErr(null); }}>{on ? "stop preview" : "show visible camera"}</button>
          <span className="hint">RTSP /avc/ch1 → MJPEG 640 px{fps ? ` · ${fps.toFixed(1)} fps` : ""} (the camera limits it to ~8 fps while the thermal stream runs; expect about a second of encoder delay)</span>
        </div>
        {on && (
          <div className="visible-box">
            <img ref={img} alt="visible camera" />
          </div>
        )}
        {err && <div className="errbox">{err}</div>}
      </>
    );
  }
  if (!p.hasVideo) return <div className="hint">This recording has no visible video.</div>;
  return (
    <div className="visible-box">
      <video ref={video} src={api.visibleVideoUrl(p.name)} muted playsInline preload="auto" />
      <div className="hint">recorded visible video{p.measuredFps ? ` · ${p.measuredFps.toFixed(1)} fps` : ""} · aligned by host clock</div>
    </div>
  );
}
