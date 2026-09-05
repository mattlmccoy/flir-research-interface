import { test } from "node:test";
import assert from "node:assert/strict";
import { eventsToMarkers, markColor, markerLegend, nearestIndex, nextMarkerTime } from "./events.ts";

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

test("annotation events with a frame_id are placed exactly at that frame and labelled by name", () => {
  const m = eventsToMarkers([
    { t_utc: "2026-09-02T10:00:00.700+00:00", type: "annotation", name: "RF ON", frame_id: 104 },
    { t_utc: "2026-09-02T10:00:00.050+00:00", type: "annotation", name: "late but exact", frame_id: 101 },
  ], TL, START);
  assert.deepEqual(m, [{ t: 0.3, label: "RF ON" }, { t: 0.1, label: "late but exact" }]);
});

test("long frozen runs (the camera's NUC) become NUC markers; single repeated frames are noise", () => {
  const m = eventsToMarkers([
    { t_utc: "2026-09-02T10:00:00.300+00:00", type: "frozen_frames", first_frame_id: 102, last_frame_id: 171, repeats: 70 },
    { t_utc: "2026-09-02T10:00:00.400+00:00", type: "frozen_frames", first_frame_id: 103, last_frame_id: 103, repeats: 1 },
  ], TL, START);
  assert.equal(m.length, 1);
  assert.equal(m[0].label, "NUC (70 fr)");
  assert.equal(m[0].t, 0.2, "first frame with id >= 102 is 103 at t=0.2");
});

test("nextMarkerTime jumps to the next / previous marker strictly beyond the current time", () => {
  const ms = [{ t: 1, label: "a" }, { t: 3, label: "b" }, { t: 5, label: "c" }];
  assert.equal(nextMarkerTime(ms, 0, 1), 1);
  assert.equal(nextMarkerTime(ms, 1, 1), 3);
  assert.equal(nextMarkerTime(ms, 3.0001, 1), 5);
  assert.equal(nextMarkerTime(ms, 5, 1), null);
  assert.equal(nextMarkerTime(ms, 5, -1), 3);
  assert.equal(nextMarkerTime(ms, 1, -1), null);
  assert.equal(nextMarkerTime([], 2, 1), null);
});

test("markerLegend lists the distinct event categories present (deduped, only present)", () => {
  const leg = markerLegend([
    { t: 1, label: "RF ON" }, { t: 2, label: "RF OFF" },
    { t: 3, label: "NUC (37 fr)" }, { t: 4, label: "RF ON" },
  ]);
  assert.deepEqual(leg.map((c) => c.label), ["RF on", "RF off", "NUC"]);
  const byLabel = Object.fromEntries(leg.map((c) => [c.label, c.color]));
  assert.notEqual(byLabel["RF off"], byLabel["NUC"], "RF off and NUC must be visually distinct");
});

test("markerLegend is empty with no markers and matches markColor for each category", () => {
  assert.deepEqual(markerLegend([]), []);
  const leg = markerLegend([{ t: 1, label: "RF OFF" }, { t: 2, label: "NUC" }, { t: 3, label: "gap 5" }]);
  for (const c of leg) {
    // the legend swatch color is the same one the ticks are drawn with
    const sampleLabel = c.label === "RF off" ? "RF OFF" : c.label === "gap" ? "gap 5" : c.label;
    assert.equal(c.color, markColor(sampleLabel));
  }
});

test("camera_state snapshots are bookkeeping, not timeline events (no marker, no legend entry)", () => {
  const evs = [
    { type: "annotation", name: "RF ON", frame_id: 101 },
    { type: "camera_state", frame_id: 105 },   // stop-time snapshot: not a real event
  ];
  const m = eventsToMarkers(evs, TL, START);
  assert.deepEqual(m.map((x) => x.label), ["RF ON"], "camera_state must not become a marker");
  assert.deepEqual(markerLegend(m).map((c) => c.label), ["RF on"], "no generic 'event' entry");
});
