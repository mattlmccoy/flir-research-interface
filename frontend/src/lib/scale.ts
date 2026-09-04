export type ScaleMode = "auto" | "manual";
export interface Range {
  min: number;
  max: number;
}

/** Frame min/max ignoring NaN; null when nothing finite. */
const ROBUST_MIN_N = 1024, ROBUST_BINS = 1024, P_LO = 0.005, P_HI = 0.995;

/**
 * Auto colour range for a frame. On a real-size frame it uses robust 0.5/99.5 percentiles so a
 * handful of over-range pixels — saturated (scene hotter than the camera's range) or wrapped
 * (a count that overflowed 16 bits and reads as extreme cold) — cannot blow the scale out. Small
 * frames fall back to exact min/max. NaN pixels are ignored; an all-NaN frame is null.
 */
export function autoScale(celsius: Float32Array): Range | null {
  let min = Infinity, max = -Infinity, n = 0;
  for (let i = 0; i < celsius.length; i++) {
    const v = celsius[i];
    if (Number.isNaN(v)) continue;
    n++;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min)) return null;
  if (n < ROBUST_MIN_N || max <= min) return { min, max };
  // histogram the values and clip the extreme tails
  const bins = new Uint32Array(ROBUST_BINS);
  const scale = (ROBUST_BINS - 1) / (max - min);
  for (let i = 0; i < celsius.length; i++) {
    const v = celsius[i];
    if (Number.isNaN(v)) continue;
    bins[((v - min) * scale) | 0]++;
  }
  const loTarget = n * P_LO, hiTarget = n * P_HI;
  let cum = 0, lo = min, hi = max;
  for (let b = 0; b < ROBUST_BINS; b++) { cum += bins[b]; if (cum >= loTarget) { lo = min + b / scale; break; } }
  cum = 0;
  for (let b = 0; b < ROBUST_BINS; b++) { cum += bins[b]; if (cum >= hiTarget) { hi = min + b / scale; break; } }
  if (hi > lo) return { min: lo, max: hi };
  return { min: lo - 0.5, max: lo + 0.5 }; // bulk collapsed to one value: a thin range around it

}

const FALLBACK: Range = { min: 0, max: 100 };

/** Manual (locked) range wins when selected; otherwise the frame's auto range; else a fallback. */
export function resolveScale(mode: ScaleMode, manual: Range, auto: Range | null): Range {
  if (mode === "manual") {
    return manual.min <= manual.max ? manual : { min: manual.max, max: manual.min };
  }
  return auto ?? FALLBACK;
}
