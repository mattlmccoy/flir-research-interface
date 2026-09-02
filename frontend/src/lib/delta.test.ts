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

test("markForKey maps r / f to RF marks and ignores everything else and inputs", () => {
  assert.equal(markForKey("r", false), "RF ON");
  assert.equal(markForKey("R", false), "RF ON");
  assert.equal(markForKey("f", false), "RF OFF");
  assert.equal(markForKey("r", true), null, "typing in an input never marks");
  assert.equal(markForKey("x", false), null);
});
