// Heating rate (°C/s) of an ROI from its live trace, and a threshold alarm on it. The rate is the
// least-squares slope over the last `windowS` seconds: a two-point difference of 15 Hz samples
// would turn camera noise (±0.1 °C) into ±1.5 °C/s swings and trip any useful threshold.

export interface Series { length: number; tAt(k: number): number; vAt(k: number): number; }

/** Least-squares slope (per second) of the points in the last `windowS` seconds; null when the
 *  window holds fewer than 3 finite points or they span under half the window (just started). */
export function slopeOver(s: Series, windowS: number): number | null {
  const n = s.length;
  if (n < 3 || !(windowS > 0)) return null;
  const tEnd = s.tAt(n - 1), t0 = tEnd - windowS;
  let k = 0, st = 0, sv = 0, stt = 0, stv = 0, tMin = tEnd;
  for (let i = n - 1; i >= 0; i--) {
    const t = s.tAt(i);
    if (t < t0) break;
    const v = s.vAt(i);
    if (!Number.isFinite(v) || !Number.isFinite(t)) continue;
    const dt = t - tEnd;  // centred near 0 for numerical stability
    k++; st += dt; sv += v; stt += dt * dt; stv += dt * v; tMin = t;
  }
  if (k < 3 || tEnd - tMin < windowS / 2) return null;
  const den = k * stt - st * st;
  return den > 0 ? (k * stv - st * sv) / den : null;
}

export type RateStat = "mean" | "max";

export interface RateAlarmConfig {
  on: boolean;
  /** Watched ROI id, or "any" to alarm on whichever ROI heats fastest. */
  roi: number | "any";
  stat: RateStat;
  /** Trip when the rate reaches this many °C/s. */
  threshold: number;
  windowS: number;
  beep: boolean;
  /** While recording, add a "rate alarm" event mark when it trips. */
  mark: boolean;
}

export const DEFAULT_RATE_ALARM: RateAlarmConfig = { on: false, roi: "any", stat: "max", threshold: 5, windowS: 2, beep: true, mark: true };
export const RATE_WINDOWS = [1, 2, 5, 10] as const;

/** Hysteresis: once tripped, the alarm re-arms only after the rate falls below this fraction. */
export const REARM_FRACTION = 0.8;

export interface RateAlarmState { tripped: boolean; roi: number | null; rate: number | null; }

/**
 * Next alarm state from the current per-ROI rates. Trips when the watched rate reaches the
 * threshold; stays tripped until it falls below REARM_FRACTION × threshold (so noise around the
 * threshold does not chatter). `roi`/`rate` name the ROI that is (or last was) over.
 */
export function evalRateAlarm(rates: Map<number, number | null>, cfg: RateAlarmConfig, prev: RateAlarmState): RateAlarmState {
  if (!cfg.on || !(cfg.threshold > 0)) return { tripped: false, roi: null, rate: null };
  let roi: number | null = null, rate: number | null = null;
  for (const [id, r] of rates) {
    if (cfg.roi !== "any" && id !== cfg.roi) continue;
    if (r !== null && Number.isFinite(r) && (rate === null || r > rate)) { roi = id; rate = r; }
  }
  if (rate === null) return prev.tripped ? prev : { tripped: false, roi: null, rate: null };
  if (rate >= cfg.threshold) return { tripped: true, roi, rate };
  if (prev.tripped && rate >= cfg.threshold * REARM_FRACTION) return { ...prev, rate: prev.roi === roi ? rate : prev.rate };
  return { tripped: false, roi, rate };
}

const KEY = "fri.rateAlarm.v1";

export function loadRateAlarm(storage: Storage | null): RateAlarmConfig {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_RATE_ALARM;
    const p = JSON.parse(raw) as Partial<RateAlarmConfig>;
    const d = DEFAULT_RATE_ALARM;
    return {
      on: typeof p.on === "boolean" ? p.on : d.on,
      roi: p.roi === "any" || (typeof p.roi === "number" && Number.isInteger(p.roi)) ? p.roi : d.roi,
      stat: p.stat === "mean" || p.stat === "max" ? p.stat : d.stat,
      threshold: typeof p.threshold === "number" && p.threshold > 0 ? p.threshold : d.threshold,
      windowS: typeof p.windowS === "number" && p.windowS > 0 ? p.windowS : d.windowS,
      beep: typeof p.beep === "boolean" ? p.beep : d.beep,
      mark: typeof p.mark === "boolean" ? p.mark : d.mark,
    };
  } catch {
    return DEFAULT_RATE_ALARM;
  }
}

export function saveRateAlarm(storage: Storage | null, cfg: RateAlarmConfig): void {
  try { storage?.setItem(KEY, JSON.stringify(cfg)); } catch { /* ignore */ }
}
