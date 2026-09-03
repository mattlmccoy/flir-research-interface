/**
 * Image-enhancement helpers from the ResearchIR feature set that are pure and frame-local:
 * scale limits from the active ROI, temporal max/min hold, and saturation counting.
 */
import { roiPixels, type Roi } from "./roi.ts";
import type { Range } from "./scale.ts";

/** Min/max of the ROI's pixels (NaN ignored); null when the ROI covers nothing. */
export function rangeFromRoi(field: Float32Array, w: number, h: number, roi: Roi): Range | null {
  let min = Infinity, max = -Infinity;
  for (const k of roiPixels(roi, w, h)) {
    const v = field[k];
    if (Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === Infinity ? null : { min, max };
}

/** Per-pixel max (or min) since the last reset ("maximum image" for peak-temperature maps). */
export class HoldBuffer {
  field: Float32Array | null = null;
  readonly mode: "max" | "min";
  constructor(mode: "max" | "min") { this.mode = mode; }
  push(c: Float32Array): Float32Array {
    if (!this.field || this.field.length !== c.length) { this.field = new Float32Array(c); return this.field; }
    const f = this.field;
    for (let i = 0; i < c.length; i++) {
      const v = c[i];
      if (Number.isNaN(v)) continue;
      if (Number.isNaN(f[i]) || (this.mode === "max" ? v > f[i] : v < f[i])) f[i] = v;
    }
    return f;
  }
  reset(): void { this.field = null; }
}

/** Pixels at or beyond the calibrated case limits (the camera cannot measure them). */
export function saturationCount(field: Float32Array, lim: { low: number; high: number }): { low: number; high: number } {
  let low = 0, high = 0;
  for (let i = 0; i < field.length; i++) {
    const v = field[i];
    if (Number.isNaN(v)) continue;
    if (v <= lim.low) low++;
    else if (v >= lim.high) high++;
  }
  return { low, high };
}
