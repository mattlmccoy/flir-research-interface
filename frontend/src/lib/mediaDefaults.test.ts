import { test } from "node:test";
import assert from "node:assert/strict";
import { defaultMaxMbForFormat, GIF_DEFAULT_MB } from "./mediaDefaults.ts";

test("switching to GIF caps an uncapped export (GIFs balloon without a limit)", () => {
  assert.equal(defaultMaxMbForFormat("gif", 0), GIF_DEFAULT_MB);
});

test("switching to MP4 lifts the auto GIF cap (H.264 is tiny)", () => {
  assert.equal(defaultMaxMbForFormat("mp4", GIF_DEFAULT_MB), 0);
});

test("an explicit user choice is preserved across format switches", () => {
  assert.equal(defaultMaxMbForFormat("gif", 50), 50); // user picked 50 MB for the GIF
  assert.equal(defaultMaxMbForFormat("mp4", 50), 50); // and it survives the switch to MP4
  assert.equal(defaultMaxMbForFormat("gif", 10), 10);
});
