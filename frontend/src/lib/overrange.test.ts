import { test } from "node:test";
import assert from "node:assert/strict";
import { overRangeMask, SAT_HI } from "./overrange.ts";

test("a normal frame has no over-range pixels", () => {
  assert.equal(overRangeMask(new Uint16Array(64).fill(29500), 8, 8), null);
});

test("saturated pixels are always flagged", () => {
  const c = new Uint16Array(64).fill(29500);
  c[10] = SAT_HI + 100;
  const r = overRangeMask(c, 8, 8)!;
  assert.equal(r.saturated, 1);
  assert.equal(r.mask[10], 1);
});

test("in a hot frame, implausibly-cold (wrapped) pixels are flagged", () => {
  const c = new Uint16Array(64).fill(30000);
  c[20] = 52000; // frame is clearly hot (>= HOT_MAX)
  c[27] = 19000; // wrapped hot-spot centre reading ~ -84 °C
  const r = overRangeMask(c, 8, 8)!;
  assert.equal(r.mask[27], 1, "wrapped pixel flagged");
  assert.ok(r.wrapped >= 1);
});

test("a wrapped (sub-floor) pixel is flagged even when nothing else in the frame is hot", () => {
  // An arc can wrap while the rest of the frame stays under ~177 °C; below -13 °C never occurs
  // in this lab (88,771 real frames: no pixel <= 26000 counts unless the frame was also hot).
  const c = new Uint16Array(64).fill(30000);
  c[27] = 19000;
  const r = overRangeMask(c, 8, 8)!;
  assert.equal(r.mask[27], 1);
  assert.equal(r.wrapped, 1);
});

test("a 100 mK frame is judged in its own units (40 °C is ~3131 counts there)", () => {
  const c = new Uint16Array(64).fill(Math.round((40 + 273.15) / 0.1));
  assert.equal(overRangeMask(c, 8, 8, 0.1), null);
  c[27] = Math.round((-80 + 273.15) / 0.1); // a wrapped reading at 100 mK
  const r = overRangeMask(c, 8, 8, 0.1)!;
  assert.equal(r.mask[27], 1);
  assert.equal(r.wrapped, 1);
});
