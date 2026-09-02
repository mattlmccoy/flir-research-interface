import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.ts";

type Props =
  | { mode: "live"; available: boolean; reason?: string }
  | { mode: "playback"; name: string; hasVideo: boolean; t: number; playing: boolean; speed: number; measuredFps?: number | null };

/**
 * Visible camera (Milestone 9 view). Live: a low-rate MJPEG relay, off by default because each
 * viewer costs one ffmpeg on the operator. Playback: the recorded visible.mp4, kept in step with
 * the thermal cursor (host-clock alignment, ~tens of ms; not frame-exact).
 */
export function VisiblePanel(p: Props) {
  // One stable URL per "show": a changing src would restart the stream (and its ffmpeg) on every render.
  const [src, setSrc] = useState<string | null>(null);
  const on = src !== null;
  const [err, setErr] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);

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
          <button className={on ? "danger" : "secondary"} onClick={() => { setSrc(on ? null : `${api.visibleLiveUrl()}?t=${Date.now()}`); setErr(null); }}>{on ? "stop preview" : "show visible camera"}</button>
          <span className="hint">RTSP /avc/ch1 → MJPEG 640 px, ~8 fps (the camera limits it while the thermal stream runs)</span>
        </div>
        {on && (
          <div className="visible-box">
            <img src={src} alt="visible camera" onError={() => setErr("stream ended or the camera refused the RTSP connection")} />
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
