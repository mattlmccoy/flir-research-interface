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

test("a cold scene is never touched (safety): sub-floor pixel without a hot frame is left alone", () => {
  const c = new Uint16Array(64).fill(30000);
  c[27] = 19000; // a lone cold/dead pixel, but the frame is not hot
  assert.equal(overRangeMask(c, 8, 8), null);
});
