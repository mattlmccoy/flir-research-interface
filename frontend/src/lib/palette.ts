/**
 * Visualization-only color lookup tables. These are "-like" palettes designed here; they are
 * not FLIR's proprietary LUTs (brief §11). Applying a palette never changes the temperature data.
 */
export type PaletteName = "iron" | "grayscale" | "blackhot" | "rainbow" | "diverging";
export const PALETTE_NAMES: readonly PaletteName[] = ["iron", "grayscale", "blackhot", "rainbow", "diverging"];

type Stop = [t: number, r: number, g: number, b: number];

const IRON_STOPS: Stop[] = [
  [0.0, 0, 0, 0],
  [0.15, 32, 0, 96],
  [0.35, 140, 0, 140],
  [0.55, 220, 60, 40],
  [0.75, 250, 150, 20],
  [0.9, 255, 220, 60],
  [1.0, 255, 255, 230],
];

const RAINBOW_STOPS: Stop[] = [
  [0.0, 0, 0, 0],
  [0.1, 20, 0, 120],
  [0.25, 0, 60, 255],
  [0.4, 0, 200, 220],
  [0.55, 0, 220, 60],
  [0.7, 230, 230, 0],
  [0.85, 255, 120, 0],
  [1.0, 255, 255, 255],
];

function interpolate(stops: Stop[]): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (k < stops.length - 2 && t > stops[k + 1][0]) k++;
    const [t0, r0, g0, b0] = stops[k];
    const [t1, r1, g1, b1] = stops[k + 1];
    const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
    lut[i * 4] = r0 + (r1 - r0) * f;
    lut[i * 4 + 1] = g0 + (g1 - g0) * f;
    lut[i * 4 + 2] = b0 + (b1 - b0) * f;
    lut[i * 4 + 3] = 255;
  }
  return lut;
}

export function buildLut(name: PaletteName): Uint8ClampedArray {
  switch (name) {
    case "iron":
      return interpolate(IRON_STOPS);
    case "rainbow":
      return interpolate(RAINBOW_STOPS);
    case "grayscale":
      return interpolate([[0, 0, 0, 0], [1, 255, 255, 255]]);
    case "blackhot":
      return interpolate([[0, 255, 255, 255], [1, 0, 0, 0]]);
    case "diverging": // blue − neutral − red, for reference-frame subtraction
      return interpolate([[0, 40, 90, 220], [0.5, 235, 235, 235], [1, 220, 50, 40]]);
  }
}

/**
 * Map °C values to RGBA through `lut` over [min, max]. Values outside are clamped to the LUT
 * ends; NaN becomes transparent. `out` must be length*4. The input array is never modified.
 */
export function mapToRgba(
  celsius: Float32Array,
  min: number,
  max: number,
  lut: Uint8ClampedArray,
  out: Uint8ClampedArray,
): void {
  const span = max - min;
  const scale = span > 0 ? 255 / span : 0;
  for (let i = 0; i < celsius.length; i++) {
    const v = celsius[i];
    const o = i * 4;
    if (Number.isNaN(v)) {
      out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0;
      continue;
    }
    let idx = span > 0 ? Math.round((v - min) * scale) : 255;
    if (idx < 0) idx = 0;
    else if (idx > 255) idx = 255;
    const l = idx * 4;
    out[o] = lut[l];
    out[o + 1] = lut[l + 1];
    out[o + 2] = lut[l + 2];
    out[o + 3] = 255;
  }
}
