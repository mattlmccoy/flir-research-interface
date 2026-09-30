import { test } from "node:test";
import assert from "node:assert/strict";
import { streamStallWarning } from "./streamStall.ts";

test("streamStallWarning: nothing while frames arrive or when not recording", () => {
  assert.equal(streamStallWarning({ state: "recording", last_frame_age_s: 0.03, stream_stalled: false, stream_stalls: 0 }), null);
  assert.equal(streamStallWarning({ state: "idle", last_frame_age_s: null, stream_stalled: false }), null);
  assert.equal(streamStallWarning({ state: "recording" }), null); // an older operator without the fields
});

test("streamStallWarning: a live stall names how long frames have been missing", () => {
  const w = streamStallWarning({ state: "recording", last_frame_age_s: 19.4, stream_stalled: true, stream_stalls: 0 });
  assert.ok(w);
  assert.equal(w.level, "err");
  assert.match(w.text, /No thermal frames for 19 s/);
  assert.match(w.text, /not complete/);
});

test("streamStallWarning: an earlier stall that recovered stays visible as a warning", () => {
  const w = streamStallWarning({ state: "recording", last_frame_age_s: 0.03, stream_stalled: false, stream_stalls: 2 });
  assert.ok(w);
  assert.equal(w.level, "warn");
  assert.match(w.text, /stalled 2× earlier in this run/);
});
