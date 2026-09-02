import type { ReactNode } from "react";
import type { RecordingStatus, Status } from "../../lib/api.ts";

interface Props { status: Status; recording: RecordingStatus | null; displayFps: number; stale: boolean; left?: ReactNode; }

function num(v: number | null | undefined, d = 1): string { return v == null || !Number.isFinite(v) ? "—" : v.toFixed(d); }

/**
 * Bottom status bar (spec §3). Never shows green; drops are red, gaps amber. The recorder's
 * counters (rec-drop, gaps) stay visible through recording, finalizing AND error — a crash
 * mid-write is exactly when the operator most needs to see the last known drop/gap counts,
 * not have them vanish. Disk-low uses the recorder's own min_free_gb, never an invented
 * constant, so the warning threshold always matches what the backend will actually refuse.
 */
export function StatusBar({ status, recording, displayFps, stale, left }: Props) {
  const state = recording?.state;
  const showRecCounters = state === "recording" || state === "finalizing" || state === "error";
  const limit = recording?.min_free_gb ?? 2;
  const low = (recording?.free_space_gb ?? Infinity) < limit;
  return (
    <footer className="statusbar">
      {left}
      <span>cam <b>{num(status.camera_fps)}</b> fps</span>
      <span>disp <b>{num(displayFps)}</b> fps</span>
      <span>rx <b>{status.frames_received ?? 0}</b></span>
      <span>viz-drop <b>{status.viz_dropped ?? 0}</b></span>
      {showRecCounters && (
        <>
          <span className={(recording?.queue_dropped ?? 0) > 0 ? "bad" : ""}>rec-drop <b>{recording?.queue_dropped ?? 0}</b></span>
          <span className={(recording?.frame_id_gaps ?? 0) > 0 ? "warnv" : ""}>gaps <b>{recording?.frame_id_gaps ?? 0}</b></span>
        </>
      )}
      {state === "error" && <span className="bad">REC ERROR — {recording?.error}</span>}
      {stale && <span className="bad">NO FRAMES</span>}
      <span className="right">
        {state === "recording" && <span className="badge rec">● REC {num(recording?.duration_s, 0)} s</span>}
        {state === "finalizing" && <span className="muted">finalizing…</span>}
        <span className={low ? "bad" : ""}>disk <b>{num(recording?.free_space_gb)}</b> GB</span>
      </span>
    </footer>
  );
}
