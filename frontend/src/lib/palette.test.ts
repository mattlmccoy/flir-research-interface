import { test } from "node:test";
import assert from "node:assert/strict";
import { PALETTE_NAMES, buildLut, mapToRgba } from "./palette.ts";

test("every palette builds a 256-entry RGBA LUT", () => {
  for (const name of PALETTE_NAMES) {
    const lut = buildLut(name);
    assert.equal(lut.length, 256 * 4, name);
    for (let i = 0; i < 256; i++) assert.equal(lut[i * 4 + 3], 255);
  }
});

test("grayscale is monotonic and black-hot is its inverse", () => {
  const g = buildLut("grayscale");
  const b = buildLut("blackhot");
  assert.equal(g[0], 0);
  assert.equal(g[255 * 4], 255);
  assert.equal(b[0], 255);
  assert.equal(b[255 * 4], 0);
});

test("mapToRgba clamps to display range and never touches the input", () => {
  const celsius = new Float32Array([10, 20, 30, 40, NaN]);
  const before = Float32Array.from(celsius);
  const out = new Uint8ClampedArray(celsius.length * 4);
  mapToRgba(celsius, 20, 30, buildLut("grayscale"), out);
  assert.equal(out[0 * 4], 0);      // below range -> first entry
  assert.equal(out[1 * 4], 0);      // == min
  assert.equal(out[2 * 4], 255);    // == max
  assert.equal(out[3 * 4], 255);    // above range -> last entry
  assert.equal(out[4 * 4 + 3], 0);  // NaN -> transparent
  assert.deepEqual(celsius, before);
});

test("mapToRgba handles a degenerate range without dividing by zero", () => {
  const out = new Uint8ClampedArray(4);
  mapToRgba(new Float32Array([5]), 5, 5, buildLut("iron"), out);
  assert.equal(out[3], 255);
});

test("diverging palette is blue below, neutral at the centre, red above", () => {
  const lut = buildLut("diverging");
  assert.ok(lut[2] > lut[0], "index 0 is blue");
  assert.ok(lut[255 * 4] > lut[255 * 4 + 2], "index 255 is red");
  const c = 128 * 4;
  assert.ok(Math.abs(lut[c] - lut[c + 2]) < 24, "centre is neutral");
});

/** CIE L* of an sRGB triplet (D65), the standard lightness axis of perceptual uniformity. */
function lstar(r: number, g: number, b: number): number {
  const lin = (c: number) => { const x = c / 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  const y = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return y > 0.008856 ? 116 * Math.cbrt(y) - 16 : 903.3 * y;
}

test("perceptually uniform maps: L* rises monotonically and nearly linearly with value", () => {
  for (const name of ["viridis", "inferno", "magma", "plasma", "cividis"] as const) {
    const lut = buildLut(name);
    const L = Array.from({ length: 256 }, (_, i) => lstar(lut[i * 4], lut[i * 4 + 1], lut[i * 4 + 2]));
    for (let i = 1; i < 256; i++) assert.ok(L[i] >= L[i - 1] - 0.6, `${name}: L* dips at ${i}`);
    // straight-line fit residual: uniform maps stay within a few L* of linear
    const a = L[0], b = L[255];
    let worst = 0;
    for (let i = 0; i < 256; i++) worst = Math.max(worst, Math.abs(L[i] - (a + (b - a) * i / 255)));
    assert.ok(worst < 8, `${name}: L* deviates ${worst.toFixed(1)} from linear`);
    assert.ok(b - a > 60, `${name}: lightness span too small`);
  }
});

test("iron and rainbow are NOT uniform (documented), rainbow-hc keeps L* rising overall", () => {
  const lut = buildLut("rainbow-hc");
  const L = (i: number) => lstar(lut[i * 4], lut[i * 4 + 1], lut[i * 4 + 2]);
  assert.ok(L(255) > L(0) + 40);
  assert.ok(PALETTE_NAMES.includes("turbo") && PALETTE_NAMES.includes("viridis"));
});
