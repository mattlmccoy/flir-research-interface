// Playback plot traces of one smart ROI from its stored series (lib/smartSeries.ts): the sample and
// ring-band mean temperatures on the °C axis, and one chosen thermal-edge dimension on the right
// axis in "size" mode (px, lib/controlOverlay.ts). Rows that are not a reading (searching, or not
// valid) are NaN gaps, never 0; holding rows are valid (spec §7b) and plot.
import type { AxisTrace } from "./controlOverlay.ts";
import { rowValid, type SmartSeries } from "./smartSeries.ts";

export type SmartDimChoice = "off" | "area" | "length" | "width";
export interface SmartTraceChoice { sample: boolean; rings: boolean; dims: SmartDimChoice; }
/** A plot trace plus the axis it belongs on. */
export type SmartTrace = AxisTrace & { axis: "temp" | "size" };

/** Ring bands are dashed in the ROI colour (as on the image); the size line has its own dash. */
export const RING_DASH = [5, 3];
export const SIZE_DASH = [10, 3, 2, 3];
const DIM_COLUMN = { area: "area_px", length: "length_px", width: "width_px" } as const;

/** Trace ids that cannot collide with ROI ids (positive), control lines (-100…) or the delta trace. */
const ringId = (roiId: number, q: number) => -(10_000 + roiId * 32 + q);
const sizeId = (roiId: number) => -(10_000 + roiId * 32 + 31);

export function smartTraces(series: SmartSeries, choose: SmartTraceChoice, roi: { id: number; label: string; color: string }): SmartTrace[] {
  const gap = (c: (number | null)[]): number[] => c.map((v, k) => (v === null || !rowValid(series, k) ? NaN : v));
  const out: SmartTrace[] = [];
  if (choose.sample) out.push({ id: roi.id, label: `${roi.label} mean`, color: roi.color, axis: "temp", t: series.t_s, v: gap(series.sample.mean) });
  if (choose.rings) {
    series.rings.forEach((g, q) => out.push({
      id: ringId(roi.id, q), label: `${roi.label} ring ${g.inner_px}–${g.outer_px} px mean`, color: roi.color,
      dash: [...RING_DASH], axis: "temp", t: series.t_s, v: gap(g.mean),
    }));
  }
  if (choose.dims !== "off") {
    out.push({
      id: sizeId(roi.id), label: `${roi.label} ${choose.dims} (px)`, color: roi.color, dash: [...SIZE_DASH],
      axis: "size", t: series.t_s, v: gap(series.dims[DIM_COLUMN[choose.dims]]),
    });
  }
  return out;
}
