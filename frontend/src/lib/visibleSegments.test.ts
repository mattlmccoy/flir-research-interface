import { test } from "node:test";
import assert from "node:assert/strict";
import { visibleSegmentAt } from "./visibleSegments.ts";

const SPLIT = {
  file: "visible.mp4",
  segments: [
    { index: 0, file: "visible.mp4", offset_s: 0, duration_s: 77 },
    { index: 1, file: "visible_001.mp4", offset_s: 95, duration_s: 160 },
  ],
};

test("a recording without segments is one file on thermal time", () => {
  assert.deepEqual(visibleSegmentAt({ file: "visible.mp4" }, 12.5), { index: 0, local: 12.5 });
});

test("thermal time maps into the segment that covers it", () => {
  assert.deepEqual(visibleSegmentAt(SPLIT, 10), { index: 0, local: 10 });
  assert.deepEqual(visibleSegmentAt(SPLIT, 100), { index: 1, local: 5 });
});

test("time inside a stream gap has no visible frame", () => {
  assert.equal(visibleSegmentAt(SPLIT, 85), null);
});

test("an unprobed segment runs until the next one starts; the last one runs on", () => {
  const vis = { segments: [{ index: 0, file: "visible.mp4", offset_s: 0, duration_s: null }, { index: 1, file: "visible_001.mp4", offset_s: 95, duration_s: null }] };
  assert.deepEqual(visibleSegmentAt(vis, 90), { index: 0, local: 90 });
  assert.deepEqual(visibleSegmentAt(vis, 500), { index: 1, local: 405 });
});
