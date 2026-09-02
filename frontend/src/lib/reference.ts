/**
 * Reference-frame subtraction (Research Studio "subtract reference"): show each pixel's change
 * relative to a captured frame. Display-only; ROI statistics and recordings stay absolute.
 */
import type { Range } from "./scale.ts";

export interface Subtraction { delta: Float32Array | null; range: Range; }

/** Symmetric range about zero for a diverging palette, never tighter than ±1 °C. */
export function DIVERGING_RANGE(absMax: number): Range {
  const m = Math.max(1, Number.isFinite(absMax) ? absMax : 1);
  return { min: -m, max: m };
}

export function subtractReference(field: Float32Array, reference: Float32Array): Subtraction {
  if (field.length !== reference.length) return { delta: null, range: DIVERGING_RANGE(1) };
  const delta = new Float32Array(field.length);
  let absMax = 0;
  for (let i = 0; i < field.length; i++) {
    const d = field[i] - reference[i];
    delta[i] = d;
    if (!Number.isNaN(d) && Math.abs(d) > absMax) absMax = Math.abs(d);
  }
  return { delta, range: DIVERGING_RANGE(absMax) };
}
