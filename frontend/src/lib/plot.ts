/** Pure helpers for the temperature-vs-time plot (spec §3 plot dock). */

export interface TimeWindow { t0: number; t1: number; }
export interface ValueRange { min: number; max: number; }
export interface TraceData { t: ArrayLike<number>; v: ArrayLike<number>; }

/** Round tick positions (1/2/5 × 10^k steps) covering [lo, hi] with about `n` intervals. */
export function niceTicks(lo: number, hi: number, n: number): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / Math.max(1, n);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
  const out: number[] = [];
  const first = Math.ceil(lo / step - 1e-9) * step;
  for (let v = first; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export function xToPx(t: number, w: TimeWindow, width: number): number {
  const span = w.t1 - w.t0;
  return span > 0 ? ((t - w.t0) / span) * width : width / 2;
}

export function yToPx(v: number, r: ValueRange, height: number): number {
  const span = r.max - r.min;
  return span > 0 ? height - ((v - r.min) / span) * height : height / 2;
}

/** Fixed-capacity time/value ring buffer; gaps are stored as NaN. Readers get copies. */
export class TraceBuffer {
  private readonly cap: number;
  private tBuf: Float64Array;
  private vBuf: Float64Array;
  private start = 0;
  private n = 0;

  constructor(maxPoints: number) {
    this.cap = Math.max(1, maxPoints);
    this.tBuf = new Float64Array(this.cap);
    this.vBuf = new Float64Array(this.cap);
  }

  push(t: number, v: number | null): void {
    const i = (this.start + this.n) % this.cap;
    this.tBuf[i] = t;
    this.vBuf[i] = v === null ? NaN : v;
    if (this.n < this.cap) this.n++;
    else this.start = (this.start + 1) % this.cap;
  }

  get length(): number { return this.n; }

  private ordered(src: Float64Array): Float64Array {
    const out = new Float64Array(this.n);
    for (let k = 0; k < this.n; k++) out[k] = src[(this.start + k) % this.cap];
    return out;
  }

  get t(): Float64Array { return this.ordered(this.tBuf); }
  get v(): Float64Array { return this.ordered(this.vBuf); }
  get lastT(): number | null { return this.n ? this.tBuf[(this.start + this.n - 1) % this.cap] : null; }
}

/** Min/max over all finite values with a 5 % margin; null when nothing is finite. */
export function valueRange(traces: TraceData[]): ValueRange | null {
  let min = Infinity, max = -Infinity;
  for (const tr of traces) {
    for (let i = 0; i < tr.v.length; i++) {
      const v = tr.v[i];
      if (!Number.isFinite(v)) continue;
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  if (!Number.isFinite(min)) return null;
  const pad = Math.max((max - min) * 0.05, 0.5);
  return { min: min - pad, max: max + pad };
}

/** Time window ending at `tLast`, `span` seconds wide (Infinity = everything since `tFirst`). */
export function visibleWindow(tLast: number, span: number, tFirst: number): TimeWindow {
  if (!Number.isFinite(span)) return { t0: tFirst, t1: tLast > tFirst ? tLast : tFirst + 1 };
  const t0 = Math.max(tFirst, tLast - span);
  return { t0, t1: Math.max(tLast, t0 + span) };
}

export const WINDOWS: number[] = [30, 60, 300, Infinity];
export function windowLabel(span: number): string { return Number.isFinite(span) ? `${span} s` : "all"; }
