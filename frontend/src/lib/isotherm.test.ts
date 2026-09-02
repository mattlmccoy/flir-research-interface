import { test } from "node:test";
import assert from "node:assert/strict";
import { applyIsotherm, DEFAULT_ISOTHERM, parseIsotherm, type Isotherm } from "./isotherm.ts";

const px = (rgba: Uint8ClampedArray, i: number) => Array.from(rgba.slice(i * 4, i * 4 + 4));

test("above / below / between paint matching pixels a solid colour and leave the rest", () => {
  const c = new Float32Array([10, 20, 30, NaN]);
  const base = () => new Uint8ClampedArray([1, 1, 1, 255, 2, 2, 2, 255, 3, 3, 3, 255, 4, 4, 4, 255]);
  let rgba = base();
  applyIsotherm(c, rgba, { mode: "above", lo: 25, hi: 100, color: "#00ff00" });
  assert.deepEqual(px(rgba, 2), [0, 255, 0, 255]);
  assert.deepEqual(px(rgba, 1), [2, 2, 2, 255]);
  assert.deepEqual(px(rgba, 3), [4, 4, 4, 255], "NaN never matches");
  rgba = base();
  applyIsotherm(c, rgba, { mode: "below", lo: 15, hi: 100, color: "#0000ff" });
  assert.deepEqual(px(rgba, 0), [0, 0, 255, 255]);
  assert.deepEqual(px(rgba, 1), [2, 2, 2, 255]);
  rgba = base();
  applyIsotherm(c, rgba, { mode: "between", lo: 15, hi: 25, color: "#ff0000" });
  assert.deepEqual(px(rgba, 1), [255, 0, 0, 255]);
  assert.deepEqual(px(rgba, 0), [1, 1, 1, 255]);
  assert.deepEqual(px(rgba, 2), [3, 3, 3, 255]);
  rgba = base();
  applyIsotherm(c, rgba, { mode: "off", lo: 0, hi: 100, color: "#ff0000" });
  assert.deepEqual(rgba, base());
});

test("parseIsotherm accepts stored state and falls back to the default", () => {
  assert.deepEqual(parseIsotherm(null), DEFAULT_ISOTHERM);
  const iso: Isotherm = { mode: "between", lo: 40, hi: 60, color: "#123456" };
  assert.deepEqual(parseIsotherm(iso), iso);
  assert.deepEqual(parseIsotherm({ mode: "sideways", lo: "x", hi: 1, color: 3 }), DEFAULT_ISOTHERM);
  assert.equal(parseIsotherm({ mode: "between", lo: 60, hi: 40, color: "#123456" }).lo, 40, "lo/hi are ordered");
});
