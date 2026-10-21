import { test } from "node:test";
import assert from "node:assert/strict";
import { deltaTrace, markForKey } from "./delta.ts";

test("deltaTrace subtracts B from A sample by sample on A's time axis (nearest B sample)", () => {
  const a = { id: 1, label: "A", color: "#fff", t: [0, 1, 2, 3], v: [10, 20, 30, 40] };
  const b = { id: 2, label: "B", color: "#000", t: [0, 1, 2, 3], v: [1, 2, 3, 4] };
  const d = deltaTrace(a, b);
  assert.deepEqual(d.t, [0, 1, 2, 3]);
  assert.deepEqual(d.v, [9, 18, 27, 36]);
  assert.equal(d.label, "A − B");
  assert.equal(d.id, -1, "virtual trace id never collides with an ROI id");
  const bShort = { ...b, t: [0, 2], v: [1, 3] };
  assert.deepEqual(deltaTrace(a, bShort).v, [9, 19, 27, 37], "uses the nearest B sample in time");
  assert.ok(Array.from(deltaTrace(a, { ...b, t: [], v: [] }).v).every(Number.isNaN), "no B samples → NaN");
});

test("markForKey maps profile hotkeys to mark labels and ignores everything else and inputs", () => {
  const marks = [{ label: "RF ON", key: "r" }, { label: "RF OFF", key: "f" }, { label: "no hotkey" }];
  assert.equal(markForKey("r", false, marks), "RF ON");
  assert.equal(markForKey("R", false, marks), "RF ON");
  assert.equal(markForKey("f", false, marks), "RF OFF");
  assert.equal(markForKey("r", true, marks), null, "typing in an input never marks");
  assert.equal(markForKey("x", false, marks), null);
  assert.equal(markForKey("Enter", false, marks), null);
});

test("deltaTrace with maxGapS: an A sample with no B sample that close is a gap, never a stale pairing", () => {
  const a = { id: 1, label: "A", color: "#fff", t: [0, 0.5, 1, 1.5, 2, 5], v: [10, 11, 12, 13, 14, 15] };
  // a 2 Hz smart trace that starts late and then stops
  const b = { id: 2, label: "B", color: "#000", t: [1, 1.5, 2], v: [1, 2, 3] };
  const d = deltaTrace(a, b, 0.25);
  assert.deepEqual(Array.from(d.v, (x) => (Number.isNaN(x) ? null : x)), [null, null, 11, 11, 11, null]);
  assert.deepEqual(deltaTrace(a, b).v[0], 9, "no max gap: nearest sample as before (playback)");
  assert.equal(deltaTrace(a, b, 0.5).v[1], 10, "the gap limit is inclusive");
});
