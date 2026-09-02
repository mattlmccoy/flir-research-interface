/** Maps recorder events (events.json) onto the recording's relative time axis for plot markers. */
import type { ExperimentEvent, Timeline } from "./api.ts";
import type { Marker } from "../components/TimePlot.tsx";

const BOOKKEEPING = new Set(["recording_started", "recording_stopped"]);

/** Index of the sample time closest to `t` (0 for an empty timeline). */
export function nearestIndex(tS: ArrayLike<number>, t: number): number {
  const n = tS.length;
  if (n === 0) return 0;
  let lo = 0, hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (tS[mid] < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(tS[lo - 1] - t) <= Math.abs(tS[lo] - t)) return lo - 1;
  return lo;
}

/**
 * frame_gap events sit at the first frame after the gap (exact, via frame_id). Other events use
 * their wall-clock offset from started_utc, which is approximate (host vs device clock) and is
 * dropped when it falls outside the recording.
 */
export function eventsToMarkers(events: ExperimentEvent[], tl: Timeline, startedUtc: string | null | undefined): Marker[] {
  const out: Marker[] = [];
  const n = tl.t_s.length;
  if (n === 0) return out;
  const start = startedUtc ? Date.parse(startedUtc) : NaN;
  const tEnd = tl.t_s[n - 1];
  for (const ev of events) {
    const type = typeof ev.type === "string" ? ev.type : "event";
    if (BOOKKEEPING.has(type)) continue;
    const label = typeof ev.name === "string" ? ev.name : type;
    if (type === "frame_gap" && typeof ev.after_frame_id === "number") {
      const i = tl.frame_id.findIndex((id) => id > (ev.after_frame_id as number));
      if (i >= 0) out.push({ t: tl.t_s[i], label: `gap ${typeof ev.missing === "number" ? ev.missing : "?"}` });
      continue;
    }
    if (typeof ev.frame_id === "number") {
      // exact: the recorder stamped the last frame it had accepted when the event happened
      const i = tl.frame_id.findIndex((id) => id >= (ev.frame_id as number));
      if (i >= 0) { out.push({ t: tl.t_s[i], label }); continue; }
    }
    if (typeof ev.t_utc !== "string" || Number.isNaN(start)) continue;
    const t = (Date.parse(ev.t_utc) - start) / 1000;
    if (!Number.isFinite(t) || t < 0 || t > tEnd) continue;
    out.push({ t, label });
  }
  return out;
}
