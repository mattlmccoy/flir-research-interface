/**
 * Plateau-equalisation AGC (ResearchIR §4.3.2): histogram equalisation with the histogram
 * clipped at a plateau so empty or sparse temperature bands cannot take all the palette.
 * plateau = 0 → linear mapping; plateau = 1 → full equalisation.
 */
import type { Range } from "./scale.ts";

export interface ValueMap { min: number; max: number; table: Uint8Array; /** value → palette index 0..255 */ index: (v: number) => number; }

export function plateauMap(c: Float32Array, range: Range, bins: number, plateau: number): ValueMap {
  const { min, max } = range;
  const span = max - min || 1;
  const n = Math.max(16, bins | 0);
  const hist = new Float64Array(n);
  let count = 0;
  for (let i = 0; i < c.length; i++) {
    const v = c[i];
    if (Number.isNaN(v)) continue;
    let b = Math.floor(((v - min) / span) * n);
    if (b < 0) b = 0; else if (b >= n) b = n - 1;
    hist[b]++; count++;
  }
  const p = Math.min(1, Math.max(0, plateau));
  // Blend: (1-p) of a flat histogram (→ linear) + p of the clipped real histogram.
  const flat = count / n || 1;
  let peak = 0;
  for (let b = 0; b < n; b++) peak = Math.max(peak, hist[b]);
  const clipAt = flat + (peak - flat) * p;  // p=1: no clipping; p=0: everything clipped to flat
  const table = new Uint8Array(n + 1);
  let acc = 0, total = 0;
  const w = new Float64Array(n);
  for (let b = 0; b < n; b++) { w[b] = (1 - p) * flat + p * Math.min(hist[b], clipAt); total += w[b]; }
  for (let b = 0; b < n; b++) { table[b] = Math.round((acc / (total || 1)) * 255); acc += w[b]; }
  table[n] = 255;
  const index = (v: number): number => {
    if (Number.isNaN(v)) return 0;
    if (v <= min) return 0;
    if (v >= max) return 255;
    const f = ((v - min) / span) * n;
    const b = Math.floor(f);
    const t = f - b;
    return Math.round(table[b] + (table[Math.min(n, b + 1)] - table[b]) * t);
  };
  return { min, max, table, index };
}

/** Like mapToRgba but through a ValueMap; NaN → transparent. */
export function applyMap(c: Float32Array, m: ValueMap, lut: Uint8ClampedArray, out: Uint8ClampedArray): void {
  for (let i = 0; i < c.length; i++) {
    const v = c[i], o = i * 4;
    if (Number.isNaN(v)) { out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0; continue; }
    const k = m.index(v) * 4;
    out[o] = lut[k]; out[o + 1] = lut[k + 1]; out[o + 2] = lut[k + 2]; out[o + 3] = 255;
  }
}
