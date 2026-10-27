// Playback plot traces of one smart ROI from its stored series (lib/smartSeries.ts): the sample and
// ring-band mean temperatures on the °C axis, and one chosen thermal-edge dimension on the right
// axis in "size" mode (px, lib/controlOverlay.ts). Rows that are not a reading (searching, or not
// valid) are NaN gaps, never 0; holding rows are valid (spec §7b) and plot.
import type { AxisTrace } from "./controlOverlay.ts";
import { rowValid, type SmartSeries, type SmartSeriesState } from "./smartSeries.ts";

export type SmartDimChoice = "off" | "area" | "length" | "width";
/** `hiddenRings`: ring outer offsets (px) switched off in the rail (display only, lib/smartView.ts). */
export interface SmartTraceChoice { sample: boolean; rings: boolean; dims: SmartDimChoice; hiddenRings?: readonly number[]; }
/** A plot trace plus the axis it belongs on. */
export type SmartTrace = AxisTrace & { axis: "temp" | "size" };

/** Ring bands are dashed in the ROI colour (as on the image); the size line has its own dash. */
export const RING_DASH = [5, 3];
export const SIZE_DASH = [10, 3, 2, 3];
/** The sample mean's lower bound while pixels are over range: dotted, in the warn colour. */
export const BOUND_DASH = [2, 3];
export const BOUND_COLOR = "var(--warn)";
const DIM_COLUMN = { area: "area_px", length: "length_px", width: "width_px" } as const;

/** Trace ids that cannot collide with ROI ids (positive), control lines (-100…) or the delta trace. */
const ringId = (roiId: number, q: number) => -(10_000 + roiId * 32 + q);
const sizeId = (roiId: number) => -(10_000 + roiId * 32 + 31);
const boundId = (roiId: number) => -(10_000 + roiId * 32 + 30);

/** The stored lower-bound mean on located over-range rows (NaN elsewhere), joined to the plotted
 *  mean at the valid rows either side, so the line runs on as a visibly different segment instead
 *  of a gap. All NaN when the series has no over-range columns. */
export function boundValues(series: SmartSeries, mean: number[]): number[] {
  const px = series.over?.sample.px, lb = series.over?.sample.mean_lb;
  const n = series.t_s.length;
  const out: number[] = new Array(n).fill(NaN);
  if (!px || !lb) return out;
  const over = (k: number) => px[k] > 0 && lb[k] !== null && series.state[k] !== "searching";
  for (let k = 0; k < n; k++) {
    if (over(k)) out[k] = lb[k]!;
    else if ((k > 0 && over(k - 1)) || (k + 1 < n && over(k + 1))) out[k] = mean[k];
  }
  return out;
}

export function smartTraces(series: SmartSeries, choose: SmartTraceChoice, roi: { id: number; label: string; color: string; stale?: boolean }): SmartTrace[] {
  const suffix = roi.stale ? " (stale)" : "";  // stale or edited since computed: never looks current
  const gap = (c: (number | null)[]): number[] => c.map((v, k) => (v === null || !rowValid(series, k) ? NaN : v));
  const out: SmartTrace[] = [];
  if (choose.sample) {
    const mean = gap(series.sample.mean);
    out.push({ id: roi.id, label: `${roi.label} mean${suffix}`, color: roi.color, axis: "temp", t: series.t_s, v: mean });
    const bound = boundValues(series, mean);
    if (bound.some((v) => Number.isFinite(v))) {
      out.push({ id: boundId(roi.id), label: `${roi.label} mean ≥ lower bound (over range)${suffix}`, color: BOUND_COLOR, dash: [...BOUND_DASH], axis: "temp", t: series.t_s, v: bound });
    }
  }
  if (choose.rings) {
    series.rings.forEach((g, q) => {
      if (choose.hiddenRings?.includes(g.outer_px)) return;  // switched off in the rail; q keeps the id stable
      out.push({
        id: ringId(roi.id, q), label: `${roi.label} ring ${g.inner_px}–${g.outer_px} px mean${suffix}`, color: roi.color,
        dash: [...RING_DASH], axis: "temp", t: series.t_s, v: gap(g.mean),
      });
    });
  }
  if (choose.dims !== "off") {
    out.push({
      id: sizeId(roi.id), label: `${roi.label} ${choose.dims} (px)${suffix}`, color: roi.color, dash: [...SIZE_DASH],
      axis: "size", t: series.t_s, v: gap(series.dims[DIM_COLUMN[choose.dims]]),
    });
  }
  return out;
}

/** Why the playback temperature plot is empty: no ROI, all hidden, a failed fetch, still loading,
 *  smart lines switched off, or the smart ROI not computed. `smart` = the visible smart ROIs'
 *  series states; `smartShown` = sample or rings ticked. */
export function plotEmptyText(o: {
  rois: { kind: string; hidden?: boolean }[]; seriesStatus: "idle" | "loading" | "error";
  smart: SmartSeriesState[]; smartShown: boolean;
}): string {
  if (!o.rois.length) return "add a spot or rectangle ROI to plot it over the whole recording";
  const shown = o.rois.filter((r) => !r.hidden);
  if (!shown.length) return "every ROI is hidden: show one (◉) to plot it";
  const plain = shown.some((r) => r.kind !== "smart");
  if (plain && o.seriesStatus === "error") return "couldn’t load the series — check the operator, then adjust an ROI to retry";
  const err = o.smart.find((st): st is Extract<SmartSeriesState, { kind: "error" }> => st.kind === "error");
  if (err) return `couldn’t load the smart ROI series: ${err.message} (use “retry loading” in the measurements panel)`;
  if ((plain && o.seriesStatus === "loading") || o.smart.some((st) => st.kind === "loading")) {
    return "loading series over the whole recording… (long recordings can take several seconds)";
  }
  if (o.smart.some((st) => st.kind === "ready") && !o.smartShown) return "nothing selected: tick smart “sample” or “rings” above the plot";
  if (o.smart.length && o.smart.every((st) => st.kind === "missing")) {
    return "smart ROI not computed for this run yet: use “compute smart ROI” in the measurements panel";
  }
  return "loading series over the whole recording… (long recordings can take several seconds)";
}
