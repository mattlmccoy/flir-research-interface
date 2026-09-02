/**
 * Isotherms (Research Studio style): paint every pixel above, below or between temperature
 * limits a solid colour on top of the palette. Pure function over the °C field so live and
 * playback share it; NaN never matches.
 */
export type IsothermMode = "off" | "above" | "below" | "between";
export interface Isotherm { mode: IsothermMode; lo: number; hi: number; color: string; }
export const DEFAULT_ISOTHERM: Isotherm = Object.freeze({ mode: "off", lo: 40, hi: 60, color: "#00ff88" }) as Isotherm;
const MODES: IsothermMode[] = ["off", "above", "below", "between"];
const HEX = /^#[0-9a-f]{6}$/i;

function rgb(hex: string): [number, number, number] {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}

/** Overwrite `rgba` in place where `celsius` matches the isotherm. `above` uses `lo`, `below` uses `lo`, `between` uses [lo, hi]. */
export function applyIsotherm(celsius: Float32Array, rgba: Uint8ClampedArray, iso: Isotherm): void {
  if (iso.mode === "off" || !HEX.test(iso.color)) return;
  const [r, g, b] = rgb(iso.color);
  const lo = Math.min(iso.lo, iso.hi), hi = Math.max(iso.lo, iso.hi);
  const n = celsius.length;
  for (let i = 0; i < n; i++) {
    const v = celsius[i];
    if (Number.isNaN(v)) continue;
    const hit = iso.mode === "above" ? v >= iso.lo : iso.mode === "below" ? v <= iso.lo : v >= lo && v <= hi;
    if (!hit) continue;
    const j = i * 4;
    rgba[j] = r; rgba[j + 1] = g; rgba[j + 2] = b; rgba[j + 3] = 255;
  }
}

export function parseIsotherm(v: unknown): Isotherm {
  if (!v || typeof v !== "object") return DEFAULT_ISOTHERM;
  const o = v as Record<string, unknown>;
  const mode = o.mode as IsothermMode;
  if (!MODES.includes(mode) || typeof o.lo !== "number" || typeof o.hi !== "number" || typeof o.color !== "string" || !HEX.test(o.color)) return DEFAULT_ISOTHERM;
  if (!Number.isFinite(o.lo) || !Number.isFinite(o.hi)) return DEFAULT_ISOTHERM;
  return { mode, lo: Math.min(o.lo, o.hi), hi: Math.max(o.lo, o.hi), color: o.color };
}
