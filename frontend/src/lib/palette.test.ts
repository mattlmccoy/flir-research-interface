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
