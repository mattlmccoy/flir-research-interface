import { test } from "node:test";
import assert from "node:assert/strict";
import { canSkipVideo, offloadHeadline, offloadRow, type OffloadDoc, type OffloadEntry } from "./offloadStatus.ts";

// Shape captured from the live operator (GET /api/storage/offload, 0.4.68) plus the entry fields
// backend/flir_research_interface/offload.py writes and the states offload.decide() returns.
const entry = (over: Partial<OffloadEntry>): OffloadEntry => ({
  collection: "rf-heating", name: "20261112_150000_run", queued: 1_000, attempts: 0,
  last_try: null, error: null, state: "move", ...over,
});
const doc = (over: Partial<OffloadDoc>): OffloadDoc => ({ enabled: true, roi_video: false, drive_connected: true, pending: [], ...over });

test("each queue state reads as plain words with a tone", () => {
  assert.deepEqual(offloadRow(entry({ state: "moving" })), { label: "moving to the SSD…", tone: "busy" });
  assert.deepEqual(offloadRow(entry({ state: "move" })), { label: "ready to move", tone: "busy" });
  assert.deepEqual(offloadRow(entry({ state: "wait:SSD not connected" })),
    { label: "waiting: SSD not connected", tone: "wait" });
  assert.deepEqual(offloadRow(entry({ state: "wait:a recording is active" })),
    { label: "waiting: a recording is active", tone: "wait" });
});

test("a failure shows its error; stuck and clash need attention", () => {
  const r = offloadRow(entry({ state: "wait:retrying soon", attempts: 2, error: "copy verification failed" }));
  assert.equal(r.tone, "wait");
  assert.equal(r.label, "waiting: retrying soon (try 2 failed: copy verification failed)");
  assert.deepEqual(offloadRow(entry({ state: "stuck", attempts: 5, error: "drive went away" })),
    { label: "gave up after 5 tries: drive went away (the run is safe on this Mac)", tone: "bad" });
  assert.equal(offloadRow(entry({ state: "clash" })).tone, "bad");
  assert.match(offloadRow(entry({ state: "clash" })).label, /already on the SSD/);
});

test("an unknown state is shown verbatim, never as healthy", () => {
  assert.deepEqual(offloadRow(entry({ state: "something new" })), { label: "something new", tone: "wait" });
});

test("headline separates off, unknown, idle, waiting and needs-attention", () => {
  assert.equal(offloadHeadline(null), "status unavailable");
  assert.equal(offloadHeadline(doc({ enabled: false })), "off: finished runs stay on this Mac");
  assert.equal(offloadHeadline(doc({})), "on: nothing waiting");
  assert.equal(offloadHeadline(doc({ pending: [entry({ state: "wait:SSD not connected" })] })), "on: 1 run waiting");
  assert.equal(offloadHeadline(doc({ pending: [entry({}), entry({ name: "b", state: "stuck", attempts: 5 })] })),
    "on: 2 runs waiting, 1 needs attention");
});

test("waiting on exports names the step and its progress, and says when a video can be skipped", () => {
  const vid = entry({ state: "wait:finishing exports", export: { step: "ROI video", done: 15_000, total: 30_000 } });
  assert.deepEqual(offloadRow(vid), { label: "waiting: rendering ROI video, 50%", tone: "wait" });
  assert.equal(canSkipVideo(vid), true);
  const csv = entry({ state: "wait:finishing exports", export: { step: "automatic ROI series export", done: 0, total: 0 } });
  assert.equal(offloadRow(csv).label, "waiting: automatic ROI series export");
  assert.equal(canSkipVideo(csv), true); // skipping ahead of time stops the video from starting
  assert.equal(canSkipVideo(entry({ state: "move" })), false);
  assert.equal(offloadRow(entry({ state: "wait:finishing exports" })).label, "waiting: finishing exports");
});
