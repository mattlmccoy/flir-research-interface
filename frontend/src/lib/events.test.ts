import { test } from "node:test";
import assert from "node:assert/strict";
import { assignLabelRows, eventsToMarkers, markColor, markerLegend, nearestIndex, nextMarkerIndex } from "./events.ts";

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

// Synthetic frames and marks: shape-only. `M_TS` has a frame every 0.1 s.
const M_TS = [0, 0.1, 0.2, 0.3, 0.4, 0.5];

test("nextMarkerIndex returns the nearest frame index strictly beyond the current one", () => {
  const ms = [{ t: 0.1, label: "a" }, { t: 0.3, label: "b" }, { t: 0.5, label: "c" }];
  assert.equal(nextMarkerIndex(ms, M_TS, 0, 1), 1);
  assert.equal(nextMarkerIndex(ms, M_TS, 1, 1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 2, 1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 5, 1), null);
  assert.equal(nextMarkerIndex(ms, M_TS, 5, -1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 4, -1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 1, -1), null);
});

test("nextMarkerIndex picks the nearest marker regardless of the order of the markers", () => {
  const ms = [{ t: 0.5, label: "c" }, { t: 0.1, label: "a" }, { t: 0.3, label: "b" }];
  assert.equal(nextMarkerIndex(ms, M_TS, 0, 1), 1);
  assert.equal(nextMarkerIndex(ms, M_TS, 5, -1), 3);
});

test("nextMarkerIndex is null with no markers, no frames or only non-finite marker times", () => {
  assert.equal(nextMarkerIndex([], M_TS, 0, 1), null);
  assert.equal(nextMarkerIndex([{ t: 0.3, label: "b" }], [], 0, 1), null);
  assert.equal(nextMarkerIndex([{ t: NaN, label: "x" }, { t: Infinity, label: "y" }], M_TS, 0, 1), null);
});

test("a mark placed between frames, snapping forward, cannot trap ◆◀", () => {
  // t = 0.27 snaps to frame 3 (0.3). From frame 3 the old time-based step found 0.27 < 0.3 again and
  // jumped to frame 3 forever; by index it is not "before" frame 3, so the walk moves on.
  const ms = [{ t: 0.1, label: "a" }, { t: 0.27, label: "wall-clock" }];
  assert.equal(nextMarkerIndex(ms, M_TS, 5, -1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 3, -1), 1);
});

test("a mark placed between frames, snapping backward, cannot trap ▶◆", () => {
  // t = 0.23 snaps to frame 2 (0.2): the old step re-found 0.23 > 0.2 forever.
  const ms = [{ t: 0.23, label: "wall-clock" }, { t: 0.5, label: "c" }];
  assert.equal(nextMarkerIndex(ms, M_TS, 0, 1), 2);
  assert.equal(nextMarkerIndex(ms, M_TS, 2, 1), 5);
});

test("two marks that snap to the same frame are one stop", () => {
  const ms = [{ t: 0.28, label: "a" }, { t: 0.31, label: "b" }, { t: 0.5, label: "c" }];
  assert.equal(nextMarkerIndex(ms, M_TS, 0, 1), 3);
  assert.equal(nextMarkerIndex(ms, M_TS, 3, 1), 5);
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

test("assignLabelRows stacks only overlapping labels, keeping input order", () => {
  // far-apart labels share row 0; a close one drops to row 1
  assert.deepEqual(assignLabelRows([{ x: 0, width: 20 }, { x: 10, width: 20 }, { x: 100, width: 20 }], 4), [0, 1, 0]);
  // three mutually overlapping stack 0,1,2
  assert.deepEqual(assignLabelRows([{ x: 0, width: 30 }, { x: 10, width: 30 }, { x: 20, width: 30 }], 4), [0, 1, 2]);
  // input given out of x-order: rows still align to the input indices
  assert.deepEqual(assignLabelRows([{ x: 100, width: 20 }, { x: 0, width: 20 }, { x: 10, width: 20 }], 4), [0, 0, 1]);
  assert.deepEqual(assignLabelRows([], 4), []);
});

test("control-telemetry samples are not timeline markers (they are the RF-power trace)", () => {
  // A run drives ~1-2 control POSTs/sec → dozens of "control" events. They must NOT each become a
  // marker, or the plot top becomes an unreadable wall of "control" labels. They're the RF-power
  // trace (plotted separately), not discrete timeline events.
  const evs = [
    { type: "annotation", name: "RF ON", frame_id: 101 },
    { type: "control", frame_id: 101, forward_w: 15.4 },
    { type: "control", frame_id: 103, forward_w: 120.0 },
    { type: "control", frame_id: 104, forward_w: 135.7 },
  ];
  const m = eventsToMarkers(evs, TL, START);
  assert.deepEqual(m.map((x) => x.label), ["RF ON"], "only RF ON is a marker; control is excluded");
  assert.deepEqual(markerLegend(m).map((c) => c.label), ["RF on"], "no 'control' or generic entry");
});
