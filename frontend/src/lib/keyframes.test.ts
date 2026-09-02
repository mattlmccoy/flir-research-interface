import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { keyframeIndex, keyframeBackgroundPosition, formatSeconds } from "./keyframes.ts";

const here = dirname(fileURLToPath(import.meta.url));
const stylesPath = join(here, "..", "styles.css");

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
  assert.equal(formatSeconds(119.96), "2:00.0");
  assert.equal(formatSeconds(59.996), "1:00.0");
});

test("styles.css does not hardcode the keyframe strip's background-size (kept in one place: the .kf inline style)", () => {
  const css = readFileSync(stylesPath, "utf8");
  assert.doesNotMatch(css, /background-size:\s*1200%/);
});
