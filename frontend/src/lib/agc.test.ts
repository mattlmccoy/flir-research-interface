import { test } from "node:test";
import assert from "node:assert/strict";
import { plateauMap, applyMap } from "./agc.ts";

test("plateauMap: a bimodal scene gets most of the palette where the pixels are", () => {
  // 900 pixels near 20 °C, 100 near 80 °C, nothing in between
  const c = new Float32Array(1000);
  for (let i = 0; i < 900; i++) c[i] = 20 + (i % 10) * 0.1;
  for (let i = 900; i < 1000; i++) c[i] = 80 + (i % 10) * 0.1;
  const m = plateauMap(c, { min: 20, max: 81 }, 256, 0.9);
  // 20.5 °C (inside the cold cluster) should land well above index 0 and 50 °C (empty gap) barely moves
  const idx = (v: number) => m.index(v);
  assert.ok(idx(20.9) > 60, `cold cluster spans little palette: ${idx(20.9)}`);
  assert.ok(idx(50) - idx(21) < 40, "the empty gap consumes almost no palette");
  assert.equal(idx(19), 0); assert.equal(idx(90), 255);
  // monotonic
  let last = -1;
  for (let v = 20; v <= 81; v += 0.25) { const i = idx(v); assert.ok(i >= last); last = i; }
});

test("plateau 1.0 (no clipping) is plain histogram equalisation; plateau→0 tends to linear", () => {
  const c = new Float32Array(256);
  for (let i = 0; i < 256; i++) c[i] = i;  // flat histogram: any AGC ≈ linear
  const lin = plateauMap(c, { min: 0, max: 255 }, 256, 0.0);
  const eq = plateauMap(c, { min: 0, max: 255 }, 256, 1.0);
  for (const v of [0, 64, 128, 200, 255]) assert.ok(Math.abs(lin.index(v) - v) <= 2 && Math.abs(eq.index(v) - v) <= 2);
});

test("applyMap writes palette entries through the map and leaves NaN transparent", () => {
  const lut = new Uint8ClampedArray(256 * 4).fill(255);
  for (let i = 0; i < 256; i++) lut[i * 4] = i;
  const c = new Float32Array([0, 255, NaN]);
  const m = plateauMap(c, { min: 0, max: 255 }, 256, 0.5);
  const out = new Uint8ClampedArray(12);
  applyMap(c, m, lut, out);
  assert.equal(out[0], m.index(0)); assert.equal(out[4], m.index(255)); assert.equal(out[11], 0);
});
