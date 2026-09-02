import { test } from "node:test";
import assert from "node:assert/strict";
import { histogram, lineProfile } from "./profile.ts";

test("lineProfile samples the line's pixels in order with distance in pixels", () => {
  // 4x1 field along y=0
  const f = new Float32Array([10, 20, 30, 40]);
  const p = lineProfile(f, 4, 1, { id: 1, kind: "line", x0: 0, y0: 0, x1: 3, y1: 0 });
  assert.deepEqual(p.v, [10, 20, 30, 40]);
  assert.deepEqual(p.d, [0, 1, 2, 3]);
  const diag = lineProfile(new Float32Array([1, 2, 3, 4]), 2, 2, { id: 2, kind: "line", x0: 0, y0: 0, x1: 1, y1: 1 });
  assert.deepEqual(diag.v, [1, 4]);
  assert.ok(Math.abs(diag.d[1] - Math.SQRT2) < 1e-9);
});

test("histogram bins the field (or an ROI) between lo and hi, NaN ignored", () => {
  const f = new Float32Array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, NaN, 100]);
  const h = histogram(f, 12, 1, null, { lo: 0, hi: 10, bins: 5 });
  assert.deepEqual(h.counts, [2, 2, 2, 2, 2]);
  assert.deepEqual(h.edges, [0, 2, 4, 6, 8, 10]);
  assert.equal(h.n, 10);
  assert.equal(h.above, 1, "values above hi are counted separately");
  const roi = histogram(f, 12, 1, { id: 1, kind: "rect", x0: 0, y0: 0, x1: 4, y1: 1 }, { lo: 0, hi: 10, bins: 5 });
  assert.deepEqual(roi.counts, [2, 2, 0, 0, 0]);
});
