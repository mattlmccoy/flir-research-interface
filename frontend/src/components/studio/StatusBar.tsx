import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, type RecordingStatus, type Status, type StorageInfo } from "../../lib/api.ts";

interface Props { status: Status; recording: RecordingStatus | null; displayFps?: number; stale?: boolean; left?: ReactNode; }

function num(v: number | null | undefined, d = 1): string { return v == null || !Number.isFinite(v) ? "—" : v.toFixed(d); }
function gb(bytes: number | undefined): string { return bytes == null ? "—" : (bytes / 1e9).toFixed(0); }

/**
 * Bottom status bar (spec §3). Never shows green; drops are red, gaps amber. The recorder's
 * counters (rec-drop, gaps) stay visible through recording, finalizing AND error — a crash
 * mid-write is exactly when the operator most needs to see the last known drop/gap counts,
 * not have them vanish. Disk-low uses the recorder's own min_free_gb, never an invented
 * constant, so the warning threshold always matches what the backend will actually refuse.
 *
 * The disk readout shows local free space, and — when an external drive is registered — the
 * drive's free space too (or a warning when it is disconnected). Manage the drive in Setup → Storage.
 */
export function StatusBar({ status, recording, displayFps = 0, stale = false, left }: Props) {
  const state = recording?.state;
  const showRecCounters = state === "recording" || state === "finalizing" || state === "error";
  const limit = recording?.min_free_gb ?? 2;
  const low = (recording?.free_space_gb ?? Infinity) < limit;
  const showCameraGroup = left === undefined;

  const [storage, setStorage] = useState<StorageInfo | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => { api.storage().then((s) => { if (alive) setStorage(s); }).catch(() => undefined); };
    tick();
    const id = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const drive = storage?.drive ?? null;

  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.health().then((h) => { if (alive) setVersion(h.app_version ?? h.version ?? null); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  return (
    <footer className="statusbar">
      {left}
      {showCameraGroup && (
        <>
          <span>cam <b>{num(status.camera_fps)}</b> fps</span>
          <span>disp <b>{num(displayFps)}</b> fps</span>
          <span>rx <b>{status.frames_received ?? 0}</b></span>
          <span>viz-drop <b>{status.viz_dropped ?? 0}</b></span>
          {stale && <span className="bad">NO FRAMES</span>}
        </>
      )}
      {showRecCounters && (
        <>
          <span className={(recording?.queue_dropped ?? 0) > 0 ? "bad" : ""}>rec-drop <b>{recording?.queue_dropped ?? 0}</b></span>
          <span className={(recording?.frame_id_gaps ?? 0) > 0 ? "warnv" : ""}>gaps <b>{recording?.frame_id_gaps ?? 0}</b></span>
        </>
      )}
      {state === "error" && <span className="bad">REC ERROR — {recording?.error}</span>}
      <span className="right">
        {state === "recording" && <span className="badge rec">● REC {num(recording?.duration_s, 0)} s</span>}
        {state === "finalizing" && <span className="muted">finalizing…</span>}
        <span className={low ? "bad" : ""} title="Free space where recordings are written (manage the offload drive in Setup → Storage)">
          {drive ? "local " : "disk "}<b>{num(recording?.free_space_gb)}</b> GB
        </span>
        {drive && (
          drive.connected
            ? <span title={`Offload drive at ${drive.mount}`}>drive <b>{gb(drive.free_bytes)}</b> GB</span>
            : <span className="warnv" title={`Registered drive ${drive.mount} is not connected`}>drive ⚠ reconnect</span>
        )}
        {version && <span className="muted" title="FLIR Research Interface version (operator build)">v{version}</span>}
      </span>
    </footer>
  );
}
