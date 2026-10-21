// The visible-video adjustment model: exposure, brightness and contrast as one linear map. Mirrors
// backend/flir_research_interface/analysis/visible_adjust.py; both are held to
// backend/tests/fixtures/visible_adjust_parity.json.
//
// For a pixel value x in [0, 1]:
//   slope     = contrast * 2^exposure_ev
//   intercept = 0.5 - 0.5 * contrast + brightness
//   y         = clip(slope * x + intercept, 0, 1)
// The browser applies the same slope and intercept to R, G and B with an SVG feComponentTransfer.
//
// uint8 mapping: for a byte u, x = u / 255 and the result is floor(y * 255 + 0.5), i.e. round half
// up. Python uses the identical expression, so the two agree on every tie (Math.round and numpy's
// round are not used).
//
// Inputs must be validated or clamped first (clampAdjust, or the backend's validate_adjust): NaN and
// infinities are not handled here and would give results that differ from Python's.

export interface VisibleAdjust {
  exposure_ev: number;
  brightness: number;
  contrast: number;
}

export const NEUTRAL_ADJUST: Readonly<VisibleAdjust> = { exposure_ev: 0, brightness: 0, contrast: 1 };

/** Inclusive [low, high] of every control. */
export const ADJUST_LIMITS: Readonly<Record<keyof VisibleAdjust, readonly [number, number]>> = {
  exposure_ev: [-3, 3],
  brightness: [-0.5, 0.5],
  contrast: [0.25, 4],
};

const KEYS = ["exposure_ev", "brightness", "contrast"] as const;

/** A control this close to its default counts as untouched (the uint8 map is the identity there). */
const NEUTRAL_EPS = 1e-6;

/** A copy of `a` with every control clamped to its limits. A missing or non-finite control becomes its default. */
export function clampAdjust(a: Readonly<Partial<VisibleAdjust>>): VisibleAdjust {
  const out: VisibleAdjust = { ...NEUTRAL_ADJUST };
  for (const k of KEYS) {
    const v = a[k];
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    const [lo, hi] = ADJUST_LIMITS[k];
    out[k] = Math.min(hi, Math.max(lo, v));
  }
  return out;
}

/** Slope and intercept of the adjustment on values in [0, 1]. */
export function adjustLinear(a: Readonly<VisibleAdjust>): { slope: number; intercept: number } {
  return {
    slope: a.contrast * 2 ** a.exposure_ev,
    intercept: 0.5 - 0.5 * a.contrast + a.brightness,
  };
}

/** The adjusted value of one 0..255 byte, rounded half up (same expression as the Python applier). */
export function applyAdjustU8(v: number, a: Readonly<VisibleAdjust>): number {
  const { slope, intercept } = adjustLinear(a);
  const y = Math.min(1, Math.max(0, slope * (v / 255) + intercept));
  return Math.floor(y * 255 + 0.5);
}

/** True when `a` equals `b` in all three controls within `eps`. */
export function adjustEqual(a: Readonly<VisibleAdjust>, b: Readonly<VisibleAdjust>, eps = 1e-6): boolean {
  return KEYS.every((k) => Math.abs(a[k] - b[k]) <= eps);
}

/** True when every control is within 1e-6 of its default. */
export function isNeutral(a: Readonly<VisibleAdjust>): boolean {
  return adjustEqual(a, NEUTRAL_ADJUST, NEUTRAL_EPS);
}
