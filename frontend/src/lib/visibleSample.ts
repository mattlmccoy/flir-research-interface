/** The post-run visible-camera analysis around the sample (exports/visible_sample.json): the flash
 *  marks on the playback scrubber and the one-line status shown in the exports block. */
import type { Marker } from "../components/TimePlot.tsx";

/** One flash at the sample: when it started, peaked and ended on the thermal clock (s). */
export interface VisibleSampleEvent {
  t_start_s: number;
  t_peak_s: number;
  t_end_s: number;
  peak_brightening: number;
  n_frames: number;
  peak_frame: number;
}

/** The parsed visible_sample.json as served in ExperimentInfo. Only the keys the UI reads: a
 *  skipped or failed run carries just `status` and `reason`. */
export interface VisibleSampleSummary {
  status: "ok" | "skipped" | "failed";
  reason: string | null;
  /** `t_first_s` / `t_last_s` are null when no frame was analysed (`coverage()` in visible_sample.py). */
  coverage?: { frames_analysed: number; t_first_s: number | null; t_last_s: number | null; gaps_over_300ms: number };
  events?: VisibleSampleEvent[];
  missing?: string[];
  plot_error?: string | null;
}

/** One playback mark per flash, at its peak, labelled with the rounded peak brightening. Empty
 *  unless the run was analysed. */
export function visibleFlashMarkers(vs: VisibleSampleSummary | null | undefined): Marker[] {
  if (!vs || vs.status !== "ok" || !Array.isArray(vs.events)) return [];
  return vs.events.map((ev) => ({ t: ev.t_peak_s, label: `visible flash +${Math.round(ev.peak_brightening)}` }));
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
    const span = c
      ? `${c.t_first_s!.toFixed(1)}–${c.t_last_s!.toFixed(1)} s analysed (${c.gaps_over_300ms} gaps > 0.3 s)`
      : "coverage unknown";
    text = `Visible sample: ${n} ${n === 1 ? "flash" : "flashes"} at the sample, ${span}`;
  }
  if (vs.missing && vs.missing.length > 0) text += `; missing video: ${vs.missing.join(", ")}`;
  if (vs.plot_error != null) text += `; plot not drawn (${vs.plot_error})`;
  return { text, error: false };
}

/** The one-line outcome of the analysis, or null when no result file exists. A run that was not
 *  analysed says why, and an analysed run says what it did not cover (no frames, missing video, no
 *  plot), so "0 flashes" is never shown for a run that did not look. */
export function visibleSampleStatusText(vs: VisibleSampleSummary | null | undefined): string | null {
  return vs ? describe(vs).text : null;
}

/** Whether the status line should be styled as an error: a failed run, or a result that could not
 *  be read. A skipped run or an analysed run with warnings is not. */
export function visibleSampleIsError(vs: VisibleSampleSummary | null | undefined): boolean {
  return vs ? describe(vs).error : false;
}
