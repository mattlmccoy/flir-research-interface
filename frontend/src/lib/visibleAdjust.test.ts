import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ADJUST_LIMITS,
  NEUTRAL_ADJUST,
  adjustEqual,
  adjustLinear,
  applyAdjustU8,
  clampAdjust,
  isNeutral,
} from "./visibleAdjust.ts";

// The same table backend/tests/test_visible_adjust.py reads: one real luma row of
// 20261020_144402_Run (frame 6141) and the slope/intercept/uint8 output the spec formula gives.
interface ParityCase {
  name: string;
  adjust: { exposure_ev: number; brightness: number; contrast: number };
  slope: number;
  intercept: number;
  expected: number[];
}
const parity = JSON.parse(
  readFileSync(new URL("../../../backend/tests/fixtures/visible_adjust_parity.json", import.meta.url), "utf8"),
) as { luma: number[]; cases: ParityCase[] };

test("parity fixture holds the real 126-pixel row and nine settings", () => {
  assert.equal(parity.luma.length, 126);
  assert.equal(parity.cases.length, 9);
});

for (const c of parity.cases) {
  test(`parity table: ${c.name}`, () => {
    const { slope, intercept } = adjustLinear(c.adjust);
    assert.ok(Math.abs(slope - c.slope) <= 1e-12, `slope ${slope} vs ${c.slope}`);
    assert.ok(Math.abs(intercept - c.intercept) <= 1e-12, `intercept ${intercept} vs ${c.intercept}`);
    assert.deepEqual(parity.luma.map((u) => applyAdjustU8(u, c.adjust)), c.expected);
  });
}

test("neutral is the identity on every uint8 value", () => {
  assert.deepEqual(adjustLinear(NEUTRAL_ADJUST), { slope: 1, intercept: 0 });
  for (let u = 0; u < 256; u++) assert.equal(applyAdjustU8(u, NEUTRAL_ADJUST), u);
});

test("defaults and limits match the spec", () => {
  assert.deepEqual(NEUTRAL_ADJUST, { exposure_ev: 0, brightness: 0, contrast: 1 });
  assert.deepEqual(ADJUST_LIMITS, { exposure_ev: [-3, 3], brightness: [-0.5, 0.5], contrast: [0.25, 4] });
});

test("adjustLinear follows slope = contrast * 2^ev and intercept = 0.5 - 0.5 * contrast + brightness", () => {
  const { slope, intercept } = adjustLinear({ exposure_ev: 2, brightness: 0.25, contrast: 0.5 });
  assert.ok(Math.abs(slope - 2) < 1e-12);
  assert.ok(Math.abs(intercept - 0.5) < 1e-12);
});

test("applyAdjustU8 clips to 0..255", () => {
  assert.equal(applyAdjustU8(0, { exposure_ev: 0, brightness: -0.5, contrast: 1 }), 0);
  assert.equal(applyAdjustU8(255, { exposure_ev: 3, brightness: 0.5, contrast: 4 }), 255);
});

test("applyAdjustU8 rounds exact ties half up, as the Python applier does", () => {
  // one stop down halves the value: 1, 3, 5, 7, 255 give y * 255 = 0.5, 1.5, 2.5, 3.5, 127.5 exactly
  const half = { exposure_ev: -1, brightness: 0, contrast: 1 };
  assert.deepEqual([1, 3, 5, 7, 255].map((u) => applyAdjustU8(u, half)), [1, 2, 3, 4, 128]);
});

test("clampAdjust limits each control and replaces missing or non-finite values with the default", () => {
  assert.deepEqual(clampAdjust({ exposure_ev: 9, brightness: -9, contrast: 99 }), {
    exposure_ev: 3, brightness: -0.5, contrast: 4,
  });
  assert.deepEqual(clampAdjust({ exposure_ev: -9, brightness: 9, contrast: 0 }), {
    exposure_ev: -3, brightness: 0.5, contrast: 0.25,
  });
  assert.deepEqual(clampAdjust({ exposure_ev: 1.5 }), { exposure_ev: 1.5, brightness: 0, contrast: 1 });
  assert.deepEqual(clampAdjust({}), NEUTRAL_ADJUST);
  assert.deepEqual(
    clampAdjust({ exposure_ev: Number.NaN, brightness: Number.POSITIVE_INFINITY, contrast: "x" as unknown as number }),
    NEUTRAL_ADJUST,
  );
});

test("clampAdjust returns a new object and leaves in-range values alone", () => {
  const a = { exposure_ev: 0.5, brightness: -0.1, contrast: 1.3 };
  const out = clampAdjust(a);
  assert.deepEqual(out, a);
  assert.notEqual(out, a);
  assert.notEqual(clampAdjust(NEUTRAL_ADJUST), NEUTRAL_ADJUST);
});

test("isNeutral is true only within 1e-6 of the defaults", () => {
  assert.equal(isNeutral(NEUTRAL_ADJUST), true);
  assert.equal(isNeutral({ exposure_ev: 5e-7, brightness: -5e-7, contrast: 1 + 5e-7 }), true);
  assert.equal(isNeutral({ exposure_ev: 0.01, brightness: 0, contrast: 1 }), false);
  assert.equal(isNeutral({ exposure_ev: 0, brightness: 0.01, contrast: 1 }), false);
  assert.equal(isNeutral({ exposure_ev: 0, brightness: 0, contrast: 1.01 }), false);
});

test("adjustEqual compares all three controls within eps (default 1e-6)", () => {
  const a = { exposure_ev: 1, brightness: 0.1, contrast: 1.5 };
  assert.equal(adjustEqual(a, { ...a }), true);
  assert.equal(adjustEqual(a, { ...a, exposure_ev: 1 + 5e-7 }), true);
  assert.equal(adjustEqual(a, { ...a, exposure_ev: 1 + 2e-6 }), false);
  assert.equal(adjustEqual(a, { ...a, brightness: 0.11 }), false);
  assert.equal(adjustEqual(a, { ...a, contrast: 1.6 }), false);
  assert.equal(adjustEqual(a, { ...a, contrast: 1.6 }, 0.2), true);
});
