/**
 * Line profiles and histograms over the °C field (Research Studio's "line" and "histogram"
 * tools). Pure functions; the same code serves live frames and playback.
 */
import { roiPixels, type Line, type Roi } from "./roi.ts";

export interface Profile { d: number[]; v: number[]; }

/** Temperature along a line ROI, Bresenham order; `d` is the distance from the start in pixels. */
export function lineProfile(field: Float32Array, w: number, h: number, roi: Line): Profile {
  const d: number[] = [], v: number[] = [];
  for (const k of roiPixels(roi, w, h)) {
    const x = k % w, y = Math.floor(k / w);
    d.push(Math.hypot(x - roi.x0, y - roi.y0));
    v.push(field[k]);
  }
  return { d, v };
}

export interface HistogramSpec { lo: number; hi: number; bins: number; }
export interface Histogram { edges: number[]; counts: number[]; n: number; below: number; above: number; }

/** Histogram of the whole field (roi null) or of an ROI's pixels; NaN ignored; hi is inclusive. */
export function histogram(field: Float32Array, w: number, h: number, roi: Roi | null, spec: HistogramSpec): Histogram {
  const bins = Math.max(1, Math.floor(spec.bins));
  const lo = Math.min(spec.lo, spec.hi), hi = Math.max(spec.lo, spec.hi);
  const width = (hi - lo) / bins || 1;
  const counts = new Array<number>(bins).fill(0);
  const edges = Array.from({ length: bins + 1 }, (_, i) => lo + i * width);
  let n = 0, below = 0, above = 0;
  const visit = (v: number) => {
    if (Number.isNaN(v)) return;
    if (v < lo) { below++; return; }
    if (v > hi) { above++; return; }
    n++;
    counts[Math.min(bins - 1, Math.floor((v - lo) / width))]++;
  };
  if (roi) for (const k of roiPixels(roi, w, h)) visit(field[k]);
  else for (let k = 0; k < field.length; k++) visit(field[k]);
  return { edges, counts, n, below, above };
}
