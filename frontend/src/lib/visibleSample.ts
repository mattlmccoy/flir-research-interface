/** The post-run visible-camera analysis around the sample (exports/visible_sample.json): the flash
 *  marks on the playback scrubber and the one-line status shown in the exports block. */
import type { Marker } from "../components/TimePlot.tsx";
import { nearestIndex } from "./events.ts";

/** One flash at the sample: when it started, peaked and ended on the thermal clock (s). */
export interface VisibleSampleEvent {
  t_start_s: number;
  t_peak_s: number;
  t_end_s: number;
  peak_brightening: number;
  n_frames: number;
  /** Frame index within the file of segment `segment` (not an index into the analysed frames, and
   *  not comparable across segments); `visible_sample.csv` has the same `segment` and `frame`. */
  peak_frame: number;
  /** Index of the visible segment (`segments[].index`) the peak frame is in. */
  segment: number;
}

/** One visible video file the analysis read. `t_start_s` is where its first packet falls on the
 *  thermal clock, measured from `anchor`: the arrival of its first frame ("first_frame"), the ffmpeg
 *  launch ("launch": runs recorded before 2026-09-30 have only that, which precedes the first frame
 *  by the RTSP connect time, so their visible times run ~1.1-1.5 s early), or the offset from the
 *  first segment ("relative", with no thermal frame to anchor to). See playback/visible_timing.py. */
export interface VisibleSampleSegment {
  index: number;
  file: string;
  t_start_s: number;
  anchor: "first_frame" | "launch" | "relative";
  frames_analysed: number;
}

/** The parsed visible_sample.json as served in ExperimentInfo. Only the keys the UI reads: a
 *  skipped or failed run carries just `status` and `reason`. */
export interface VisibleSampleSummary {
  status: "ok" | "skipped" | "failed";
  reason: string | null;
  /** `t_first_s` / `t_last_s` / `uncovered_s` / `longest_gap_s` are null when no frame was analysed
   *  (`coverage()` in visible_sample.py). `uncovered_s` is the total of the spacings over 0.3 s between
   *  analysed frames, `longest_gap_s` the longest spacing; results written before they existed lack both. */
  coverage?: {
    frames_analysed: number; t_first_s: number | null; t_last_s: number | null; gaps_over_300ms: number;
    uncovered_s?: number | null; longest_gap_s?: number | null;
  };
  events?: VisibleSampleEvent[];
  segments?: VisibleSampleSegment[];
  /** Segment files visible.json lists that are not on disk. */
  missing?: string[];
  /** Segment files on disk with nothing to analyse: no video packet, or every frame inside the
   *  start-up skip. They are not in `segments` and get no close-up. */
  empty?: string[];
  plot_error?: string | null;
}

/** One playback mark per flash, labelled with the rounded peak brightening. Empty unless the run
 *  was analysed.
 *
 *  Each mark sits on the thermal frame nearest the flash peak (`tS` is the recording's frame times),
 *  like the marks eventsToMarkers places. The raw peak time usually falls between two frames, and the
 *  player snaps a jump to the nearest frame: a mark just after a frame would snap back to it and
 *  "next mark" would stay on that frame forever. Peaks that are not finite, or outside
 *  [tS[0], tS[last]], are dropped, as eventsToMarkers drops its out-of-recording events. */
export function visibleFlashMarkers(vs: VisibleSampleSummary | null | undefined, tS: ArrayLike<number>): Marker[] {
  if (!vs || vs.status !== "ok" || !Array.isArray(vs.events) || tS.length === 0) return [];
  const first = tS[0], last = tS[tS.length - 1];
  const out: Marker[] = [];
  for (const ev of vs.events) {
    const t = ev.t_peak_s;
    if (!Number.isFinite(t) || t < first || t > last) continue;
    out.push({ t: tS[nearestIndex(tS, t)], label: `visible flash +${Math.round(ev.peak_brightening)}` });
  }
  return out;
}

interface StatusLine { text: string; error: boolean; }

/** The status line and whether it is an error. Only a summary that is positively an analysed run
 *  with an events list reads as a result; a missing or unknown status, or no events list, is
 *  reported as unreadable rather than as "0 flashes". */
function describe(vs: VisibleSampleSummary): StatusLine {
  const status: unknown = vs.status;
  if (status === "skipped") return { text: `Visible sample: not analysed (${vs.reason ?? "no reason recorded"})`, error: false };
  if (status === "failed") return { text: `Visible sample: analysis failed (${vs.reason ?? "no reason recorded"})`, error: true };
  if (status !== "ok") {
    const shown = status === undefined || status === null || status === "" ? "missing" : String(status);
    return { text: `Visible sample: unreadable result (status ${shown})`, error: true };
  }
  if (!Array.isArray(vs.events)) return { text: "Visible sample: unreadable result (no events list)", error: true };
  const c = vs.coverage;
  let text: string;
  if (c && (c.frames_analysed === 0 || c.t_first_s == null || c.t_last_s == null)) {
    text = "Visible sample: 0 frames analysed, nothing to measure";
  } else {
    const n = vs.events.length;
    const lost = c && c.uncovered_s != null && c.longest_gap_s != null
      ? `, ${c.uncovered_s.toFixed(1)} s uncovered, longest ${c.longest_gap_s.toFixed(2)} s`
      : "";
    const span = c
      ? `${c.t_first_s!.toFixed(1)}–${c.t_last_s!.toFixed(1)} s analysed (${c.gaps_over_300ms} gaps > 0.3 s${lost})`
      : "coverage unknown";
    text = `Visible sample: ${n} ${n === 1 ? "flash" : "flashes"} at the sample, ${span}`;
  }
  if (Array.isArray(vs.segments) && vs.segments.some((s) => s.anchor !== "first_frame")) {
    text += "; visible times from ffmpeg launch (~1 s early)";
  }
  if (vs.missing && vs.missing.length > 0) text += `; missing video: ${vs.missing.join(", ")}`;
  if (vs.empty && vs.empty.length > 0) text += `; empty video: ${vs.empty.join(", ")}`;
  if (vs.plot_error != null) text += `; plot not drawn (${vs.plot_error})`;
  return { text, error: false };
}

/** The one-line outcome of the analysis, or null when no result file exists. A run that was not
 *  analysed says why, and an analysed run says what it did not cover (no frames, missing or empty
 *  video, no plot) and how its times were anchored, so "0 flashes" is never shown for a run that did
 *  not look. */
export function visibleSampleStatusText(vs: VisibleSampleSummary | null | undefined): string | null {
  return vs ? describe(vs).text : null;
}

/** Whether the status line should be styled as an error: a failed run, or a result that could not
 *  be read. A skipped run or an analysed run with warnings is not. */
export function visibleSampleIsError(vs: VisibleSampleSummary | null | undefined): boolean {
  return vs ? describe(vs).error : false;
}

/** `base` (the recorder's event marks) plus the visible flash marks, in time order. */
export function markersWithFlashes(base: Marker[], vs: VisibleSampleSummary | null | undefined, tS: ArrayLike<number>): Marker[] {
  return [...base, ...visibleFlashMarkers(vs, tS)].sort((a, b) => a.t - b.t);
}
