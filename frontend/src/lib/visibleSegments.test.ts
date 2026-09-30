import { test } from "node:test";
import assert from "node:assert/strict";
import { FRAME0_SKIP_S, visibleForPlayback, visibleSegmentAt } from "./visibleSegments.ts";

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

// Captured from 20260928_193907_Run: the visible file opened 24.15 s after thermal frame 0
// (pre-trigger + 3 failed RTSP opens); the operator reports it as info.visible_timeline.
const RUN_193907 = { segments: [{ index: 0, file: "visible.mp4", offset_s: 0, t_start_s: 24.15338, duration_s: 231.877411 }] };

test("a segment placed on the thermal clock is entered at its own start time", () => {
  const at = visibleSegmentAt(RUN_193907, 100);
  assert.ok(at);
  assert.equal(at.index, 0);
  assert.ok(Math.abs(at.local - 75.84662) < 1e-9);
});

test("the torn first frame is never shown: local time starts past FRAME0_SKIP_S", () => {
  assert.deepEqual(visibleSegmentAt(RUN_193907, 24.2), { index: 0, local: FRAME0_SKIP_S });
  assert.deepEqual(visibleSegmentAt({ file: "visible.mp4" }, 0), { index: 0, local: FRAME0_SKIP_S });
  assert.deepEqual(visibleSegmentAt(SPLIT, 95), { index: 1, local: FRAME0_SKIP_S });
});

test("before the video starts the first clean frame is held", () => {
  assert.deepEqual(visibleSegmentAt(RUN_193907, 3), { index: 0, local: FRAME0_SKIP_S });
});

test("playback uses the operator's thermal-clock timeline, else the recorded visible.json", () => {
  const visible = { file: "visible.mp4", segments: [{ index: 0, file: "visible.mp4", offset_s: 0, duration_s: 231.877411 }] };
  assert.deepEqual(visibleForPlayback({ visible, visible_timeline: RUN_193907.segments }), { file: "visible.mp4", segments: RUN_193907.segments });
  assert.deepEqual(visibleForPlayback({ visible }), visible); // an operator from before the timeline
  assert.equal(visibleForPlayback({ visible: null }), null);
});
