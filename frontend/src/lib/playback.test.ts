import { test } from "node:test";
import assert from "node:assert/strict";
import { clampIndex, nextFrameDelayMs, speedLabel } from "./playback.ts";

test("nextFrameDelayMs paces by recorded timestamps divided by speed", () => {
  assert.equal(nextFrameDelayMs(0.0, 0.033, 1), 33);
  assert.equal(nextFrameDelayMs(0.0, 0.033, 2), 16.5);
  assert.equal(nextFrameDelayMs(0.0, 0.033, 0.5), 66);
});

test("nextFrameDelayMs never returns a negative or absurd delay", () => {
  assert.equal(nextFrameDelayMs(5, 4, 1), 0);        // out-of-order timestamps -> immediate
  assert.equal(nextFrameDelayMs(0, 100, 1), 2000);    // cap gaps (e.g. camera pause) at 2 s
  assert.equal(nextFrameDelayMs(0, 0.033, Infinity), 0);
});

test("clampIndex keeps the cursor inside the experiment", () => {
  assert.equal(clampIndex(-1, 10), 0);
  assert.equal(clampIndex(10, 10), 9);
  assert.equal(clampIndex(4, 10), 4);
  assert.equal(clampIndex(0, 0), 0);
});

test("speedLabel", () => {
  assert.equal(speedLabel(1), "1×");
  assert.equal(speedLabel(0.25), "0.25×");
  assert.equal(speedLabel(Infinity), "max");
});
