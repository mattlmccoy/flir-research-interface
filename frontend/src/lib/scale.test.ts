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
