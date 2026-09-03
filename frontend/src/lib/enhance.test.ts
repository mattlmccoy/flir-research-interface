import { test } from "node:test";
import assert from "node:assert/strict";
import { HoldBuffer, rangeFromRoi, saturationCount } from "./enhance.ts";

test("rangeFromRoi: min/max of the ROI's pixels (NaN ignored), null when empty", () => {
  const f = new Float32Array([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.deepEqual(rangeFromRoi(f, 3, 3, { id: 1, kind: "rect", x0: 1, y0: 1, x1: 3, y1: 3 }), { min: 5, max: 9 });
  assert.equal(rangeFromRoi(f, 3, 3, { id: 2, kind: "rect", x0: 5, y0: 5, x1: 6, y1: 6 }), null);
});

test("HoldBuffer keeps the per-pixel max (or min) since reset", () => {
  const h = new HoldBuffer("max");
  h.push(new Float32Array([1, 5, NaN]));
  h.push(new Float32Array([3, 2, 7]));
  assert.deepEqual(Array.from(h.field!), [3, 5, 7]);
  h.reset();
  assert.equal(h.field, null);
  const m = new HoldBuffer("min");
  m.push(new Float32Array([1, 5])); m.push(new Float32Array([3, 2]));
  assert.deepEqual(Array.from(m.field!), [1, 2]);
  m.push(new Float32Array([1, 2, 3]));  // size change resets
  assert.deepEqual(Array.from(m.field!), [1, 2, 3]);
});

test("saturationCount counts pixels at or beyond the calibrated case limits", () => {
  const f = new Float32Array([-25, 10, 250.5, 100, NaN]);
  assert.deepEqual(saturationCount(f, { low: -20, high: 250 }), { low: 1, high: 1 });
});
