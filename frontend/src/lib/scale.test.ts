import { test } from "node:test";
import assert from "node:assert/strict";
import { autoScale, resolveScale } from "./scale.ts";

test("autoScale returns finite min/max ignoring NaN", () => {
  const r = autoScale(new Float32Array([NaN, 30, 20, 25]));
  assert.deepEqual(r, { min: 20, max: 30 });
});

test("autoScale of an all-NaN frame is null", () => {
  assert.equal(autoScale(new Float32Array([NaN, NaN])), null);
});

test("resolveScale prefers manual when locked, else auto, else fallback", () => {
  const auto = { min: 20, max: 30 };
  assert.deepEqual(resolveScale("manual", { min: 150, max: 220 }, auto), { min: 150, max: 220 });
  assert.deepEqual(resolveScale("auto", { min: 150, max: 220 }, auto), auto);
  assert.deepEqual(resolveScale("auto", { min: 150, max: 220 }, null), { min: 0, max: 100 });
});

test("resolveScale repairs an inverted manual range", () => {
  assert.deepEqual(resolveScale("manual", { min: 220, max: 150 }, null), { min: 150, max: 220 });
});

test("autoScale ignores a few over-range outliers on a real-size frame (robust percentiles)", () => {
  // 2000 px at 25 °C, plus wrapped (-500) and saturated (400) outliers that must not blow the range
  const a = new Float32Array(2010);
  a.fill(25);
  for (let i = 2000; i < 2005; i++) a[i] = -500; // wrapped hot pixels reading cold
  for (let i = 2005; i < 2010; i++) a[i] = 400;  // saturated
  const r = autoScale(a)!;
  assert.ok(r.min > -50 && r.max < 100, `robust range excludes outliers: got ${r.min}..${r.max}`);
});

test("autoScale keeps exact min/max for small frames (no robustening)", () => {
  const r = autoScale(new Float32Array([20, 25, 30]))!;
  assert.deepEqual(r, { min: 20, max: 30 });
});
