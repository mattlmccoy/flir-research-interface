export type ScaleMode = "auto" | "manual";
export interface Range {
  min: number;
  max: number;
}

/** Frame min/max ignoring NaN; null when nothing finite. */
export function autoScale(celsius: Float32Array): Range | null {
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < celsius.length; i++) {
    const v = celsius[i];
    if (Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return Number.isFinite(min) ? { min, max } : null;
}

const FALLBACK: Range = { min: 0, max: 100 };

/** Manual (locked) range wins when selected; otherwise the frame's auto range; else a fallback. */
export function resolveScale(mode: ScaleMode, manual: Range, auto: Range | null): Range {
  if (mode === "manual") {
    return manual.min <= manual.max ? manual : { min: manual.max, max: manual.min };
  }
  return auto ?? FALLBACK;
}
