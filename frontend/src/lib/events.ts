/** Maps recorder events (events.json) onto the recording's relative time axis for plot markers. */
import type { ExperimentEvent, Timeline } from "./api.ts";
import type { Marker } from "../components/TimePlot.tsx";

// Internal bookkeeping events, not things that "happened" on the timeline: the start/stop records
// and the camera_state snapshot written at stop (device temperature, NUC count). No tick, no legend.
const BOOKKEEPING = new Set(["recording_started", "recording_stopped", "camera_state"]);
/** Frozen runs at least this long are shown as a NUC marker. */
export const NUC_MIN_REPEATS = 10;

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
    if (type === "frozen_frames") {
      // The A70 repeats its last image for ~2 s (60-70 frames) during a NUC; isolated repeats
      // (1-2 frames) happen ~1 % of the time and are not worth a marker.
      const repeats = typeof ev.repeats === "number" ? ev.repeats : 0;
      if (repeats < NUC_MIN_REPEATS || typeof ev.first_frame_id !== "number") continue;
      const i = tl.frame_id.findIndex((id) => id >= (ev.first_frame_id as number));
      if (i >= 0) out.push({ t: tl.t_s[i], label: `NUC (${repeats} fr)` });
      continue;
    }
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

/** The event categories shown as timeline ticks, each with a legend label and a distinct color.
 *  Order here is the legend order. Colors must be visually distinct so a viewer can tell RF off
 *  (amber) from a NUC (blue) at a glance. Shared by the playback scrubber and media-export bar. */
interface MarkerCat { label: string; color: string; match: (upper: string) => boolean; }
const MARKER_CATS: MarkerCat[] = [
  { label: "RF on", color: "var(--live)", match: (l) => l.includes("RF") && l.includes("ON") },
  { label: "RF off", color: "var(--warn)", match: (l) => l.includes("RF") && l.includes("OFF") },
  { label: "NUC", color: "var(--trace-3)", match: (l) => l.includes("NUC") },
  { label: "gap", color: "var(--err)", match: (l) => l.includes("GAP") },
];
const OTHER_CAT = { label: "event", color: "var(--fg-strong)" };

/** Theme-token color for an event marker by its label (RF on/off, NUC, gap, other). */
export function markColor(label: string): string {
  const l = label.toUpperCase();
  return MARKER_CATS.find((c) => c.match(l))?.color ?? OTHER_CAT.color;
}

/** The distinct event categories present in `markers`, in legend order, as {label, color}. Adds a
 *  generic "event" entry when some marker matches no known category. Empty when there are none. */
export function markerLegend(markers: Marker[]): { label: string; color: string }[] {
  const uppers = markers.map((m) => m.label.toUpperCase());
  const out = MARKER_CATS.filter((c) => uppers.some((l) => c.match(l)))
    .map((c) => ({ label: c.label, color: c.color }));
  if (uppers.some((l) => !MARKER_CATS.some((c) => c.match(l)))) out.push({ ...OTHER_CAT });
  return out;
}

/** Time of the next (dir = 1) or previous (dir = -1) marker strictly beyond `t`, or null. */
export function nextMarkerTime(markers: Marker[], t: number, dir: 1 | -1): number | null {
  const eps = 1e-6;
  const cands = markers.map((m) => m.t).filter((mt) => (dir === 1 ? mt > t + eps : mt < t - eps));
  if (cands.length === 0) return null;
  return dir === 1 ? Math.min(...cands) : Math.max(...cands);
}
