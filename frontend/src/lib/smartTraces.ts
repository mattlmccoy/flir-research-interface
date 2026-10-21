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
const DIM_COLUMN = { area: "area_px", length: "length_px", width: "width_px" } as const;

/** Trace ids that cannot collide with ROI ids (positive), control lines (-100…) or the delta trace. */
const ringId = (roiId: number, q: number) => -(10_000 + roiId * 32 + q);
const sizeId = (roiId: number) => -(10_000 + roiId * 32 + 31);

export function smartTraces(series: SmartSeries, choose: SmartTraceChoice, roi: { id: number; label: string; color: string; stale?: boolean }): SmartTrace[] {
  const suffix = roi.stale ? " (stale)" : "";  // stale or edited since computed: never looks current
  const gap = (c: (number | null)[]): number[] => c.map((v, k) => (v === null || !rowValid(series, k) ? NaN : v));
  const out: SmartTrace[] = [];
  if (choose.sample) out.push({ id: roi.id, label: `${roi.label} mean${suffix}`, color: roi.color, axis: "temp", t: series.t_s, v: gap(series.sample.mean) });
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
