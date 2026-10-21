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
  coverage?: { frames_analysed: number; t_first_s: number; t_last_s: number; gaps_over_300ms: number };
  events?: VisibleSampleEvent[];
  missing?: string[];
  plot_error?: string | null;
}

/** One playback mark per flash, at its peak, labelled with the rounded peak brightening. Empty
 *  unless the run was analysed. */
export function visibleFlashMarkers(vs: VisibleSampleSummary | null | undefined): Marker[] {
  if (!vs || vs.status !== "ok") return [];
  return (vs.events ?? []).map((ev) => ({ t: ev.t_peak_s, label: `visible flash +${Math.round(ev.peak_brightening)}` }));
}

/** The one-line outcome of the analysis, or null when no result file exists. A run that was not
 *  analysed says why, and an analysed run says what it did not cover (missing video, no plot), so
 *  "0 flashes" is never shown for a run that did not look. */
export function visibleSampleStatusText(vs: VisibleSampleSummary | null | undefined): string | null {
  if (!vs) return null;
  if (vs.status === "skipped") return `Visible sample: not analysed (${vs.reason ?? "no reason recorded"})`;
  if (vs.status === "failed") return `Visible sample: analysis failed (${vs.reason ?? "no reason recorded"})`;
  const n = vs.events?.length ?? 0;
  const c = vs.coverage;
  const span = c
    ? `${c.t_first_s.toFixed(1)}–${c.t_last_s.toFixed(1)} s analysed (${c.gaps_over_300ms} gaps > 0.3 s)`
    : "coverage unknown";
  let text = `Visible sample: ${n} ${n === 1 ? "flash" : "flashes"} at the sample, ${span}`;
  if (vs.missing && vs.missing.length > 0) text += `; missing video: ${vs.missing.join(", ")}`;
  if (vs.plot_error != null) text += `; plot not drawn (${vs.plot_error})`;
  return text;
}
