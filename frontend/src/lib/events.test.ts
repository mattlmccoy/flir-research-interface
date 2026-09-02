import { test } from "node:test";
import assert from "node:assert/strict";
import { eventsToMarkers, nearestIndex } from "./events.ts";

const TL = { t_s: [0, 0.1, 0.2, 0.3, 0.4], frame_id: [100, 101, 103, 104, 105] };
const START = "2026-09-02T10:00:00.000+00:00";

test("frame_gap events are placed at the first frame after the gap and labelled with the count", () => {
  const m = eventsToMarkers([{ t_utc: "2026-09-02T10:00:00.250+00:00", type: "frame_gap", after_frame_id: 101, missing: 1 }], TL, START);
  assert.deepEqual(m, [{ t: 0.2, label: "gap 1" }]);
});

test("recording start/stop bookkeeping events are not markers", () => {
  const m = eventsToMarkers([
    { t_utc: START, type: "recording_started" },
    { t_utc: "2026-09-02T10:00:00.400+00:00", type: "recording_stopped" },
  ], TL, START);
  assert.deepEqual(m, []);
});

test("other timed events fall back to wall-clock offset from started_utc, clamped to the recording", () => {
  const m = eventsToMarkers([
    { t_utc: "2026-09-02T10:00:00.300+00:00", type: "nuc" },
    { t_utc: "2026-09-02T10:00:09.000+00:00", type: "late" },
    { type: "no_time" },
  ], TL, START);
  assert.equal(m.length, 1);
  assert.ok(Math.abs(m[0].t - 0.3) < 1e-9);
  assert.equal(m[0].label, "nuc");
});

test("nearestIndex finds the closest sample time", () => {
  assert.equal(nearestIndex(TL.t_s, -1), 0);
  assert.equal(nearestIndex(TL.t_s, 0.26), 3);
  assert.equal(nearestIndex(TL.t_s, 0.24), 2);
  assert.equal(nearestIndex(TL.t_s, 9), 4);
  assert.equal(nearestIndex([], 1), 0);
});
