import { test } from "node:test";
import assert from "node:assert/strict";
import { boxBlur, median3 } from "./filters.ts";

test("boxBlur smooths and keeps NaN out of the average", () => {
  const f = new Float32Array([0, 0, 0, 0, 9, 0, 0, 0, 0]);
  const out = boxBlur(f, 3, 3, 1);
  assert.ok(Math.abs(out[4] - 1) < 1e-6, "centre = mean of 9");
  assert.ok(Math.abs(out[0] - 9 / 4) < 1e-6, "corner = mean of its 4 in-bounds neighbours");
  const g = new Float32Array([1, NaN, 3]);
  const o = boxBlur(g, 3, 1, 1);
  assert.ok(Math.abs(o[0] - 1) < 1e-6 && Math.abs(o[2] - 3) < 1e-6 && Number.isNaN(o[1]));
});

test("median3 removes an isolated spike", () => {
  const f = new Float32Array([1, 1, 1, 1, 99, 1, 1, 1, 1]);
  assert.equal(median3(f, 3, 3)[4], 1);
  assert.equal(median3(f, 3, 3)[0], 1);
});
