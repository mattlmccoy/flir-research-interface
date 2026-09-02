import { test } from "node:test";
import assert from "node:assert/strict";
import { keyframeIndex, keyframeBackgroundPosition, formatSeconds } from "./keyframes.ts";

test("keyframeIndex maps mouse x across the width to 0..count-1", () => {
  assert.equal(keyframeIndex(0, 300, 12), 0);
  assert.equal(keyframeIndex(299, 300, 12), 11);
  assert.equal(keyframeIndex(150, 300, 12), 6);
  assert.equal(keyframeIndex(-5, 300, 12), 0);
  assert.equal(keyframeIndex(1000, 300, 12), 11);
  assert.equal(keyframeIndex(10, 0, 12), 0);
});

test("keyframeBackgroundPosition selects tile k of a horizontal strip", () => {
  assert.equal(keyframeBackgroundPosition(0, 12), "0% 0");
  assert.equal(keyframeBackgroundPosition(11, 12), "100% 0");
  assert.match(keyframeBackgroundPosition(6, 12), /^54\.5\d+% 0$/);
});

test("formatSeconds", () => {
  assert.equal(formatSeconds(3.8961), "3.90 s");
  assert.equal(formatSeconds(75.2), "1:15.2");
});
