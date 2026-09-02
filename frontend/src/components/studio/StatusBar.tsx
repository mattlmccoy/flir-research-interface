import type { ReactNode } from "react";
import type { RecordingStatus, Status } from "../../lib/api.ts";

interface Props { status: Status; recording: RecordingStatus | null; displayFps: number; stale: boolean; left?: ReactNode; }

function num(v: number | null | undefined, d = 1): string { return v == null ? "—" : v.toFixed(d); }

/** Bottom status bar (spec §3). Never shows green; drops are red, gaps amber. */
export function StatusBar({ status, recording, displayFps, stale, left }: Props) {
  const rec = recording?.state === "recording";
  return (
    <footer className="statusbar">
      {left}
      <span>cam <b>{num(status.camera_fps)}</b> fps</span>
      <span>disp <b>{num(displayFps)}</b> fps</span>
      <span>rx <b>{status.frames_received ?? 0}</b></span>
      <span>viz-drop <b>{status.viz_dropped ?? 0}</b></span>
      {rec && (
        <>
          <span className={(recording?.queue_dropped ?? 0) > 0 ? "bad" : ""}>rec-drop <b>{recording?.queue_dropped ?? 0}</b></span>
          <span className={(recording?.frame_id_gaps ?? 0) > 0 ? "warnv" : ""}>gaps <b>{recording?.frame_id_gaps ?? 0}</b></span>
        </>
      )}
      {stale && <span className="bad">NO FRAMES</span>}
      <span className="right">
        {rec && <span className="badge rec">● REC {num(recording?.duration_s, 0)} s</span>}
        <span className={(recording?.free_space_gb ?? Infinity) < 5 ? "bad" : ""}>disk <b>{num(recording?.free_space_gb)}</b> GB</span>
      </span>
    </footer>
  );
}
