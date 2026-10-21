import assert from "node:assert/strict";
import { test } from "node:test";
import { parseSmartView, smartPrefs, toggleSmartExpanded, toggleSmartRing, visibleOutlineRings, visibleRings } from "./smartView.ts";

test("prefs default to collapsed with every ring shown", () => {
  assert.deepEqual(smartPrefs({}, "live", 3), { expanded: false, hiddenRings: [] });
});

test("expanded and hidden rings are kept per ROI id", () => {
  let v = toggleSmartExpanded({}, "live", 3);
  v = toggleSmartRing(v, "live", 3, 10);
  v = toggleSmartRing(v, "live", 4, 25);
  assert.deepEqual(smartPrefs(v, "live", 3), { expanded: true, hiddenRings: [10] });
  assert.deepEqual(smartPrefs(v, "live", 4), { expanded: false, hiddenRings: [25] });
  v = toggleSmartRing(v, "live", 3, 10);
  v = toggleSmartExpanded(v, "live", 3);
  assert.deepEqual(smartPrefs(v, "live", 3), { expanded: false, hiddenRings: [] }, "toggling twice restores");
});

test("toggles never mutate the previous state", () => {
  const before = toggleSmartRing({}, "live", 3, 5);
  const frozen = JSON.stringify(before);
  toggleSmartRing(before, "live", 3, 10);
  toggleSmartExpanded(before, "live", 3);
  assert.equal(JSON.stringify(before), frozen);
});

test("parseSmartView keeps only well-formed entries (stored layout may be old or hand-edited)", () => {
  assert.deepEqual(parseSmartView(null), {});
  assert.deepEqual(parseSmartView("x"), {});
  assert.deepEqual(parseSmartView({ "live:3": { expanded: true, hiddenRings: [5, "x", 10.5, 25] }, "live:abc": { expanded: true }, "live:4": 7 }),
    { "live:3": { expanded: true, hiddenRings: [5, 25] } });
});

test("visibleRings drops the hidden bands from the readout and the plot", () => {
  const rings = [{ inner_px: 0, outer_px: 5 }, { inner_px: 5, outer_px: 10 }, { inner_px: 10, outer_px: 25 }];
  assert.deepEqual(visibleRings(rings, [10]).map((g) => g.outer_px), [5, 25]);
  assert.equal(visibleRings(rings, []), rings, "nothing hidden: same array (no re-render churn)");
});

test("visibleOutlineRings: outline ring q is the ROI's rings_px[q]; an unknown ring stays drawn", () => {
  const loops = ["r5", "r10", "r25"];
  assert.deepEqual(visibleOutlineRings(loops, [5, 10, 25], [5, 25]), ["r10"]);
  assert.deepEqual(visibleOutlineRings(loops, [5, 10], [25]), loops, "a stored outline with more rings than the ROI: never hide a ring we cannot name");
});

// --- review round: prefs are scoped like labelScope ("live" / "exp.<name>") ---
test("the same ROI id in live and in a run keeps separate prefs", () => {
  let v = toggleSmartRing({}, "live", 1, 10);
  v = toggleSmartExpanded(v, "exp.run_a", 1);
  assert.deepEqual(smartPrefs(v, "live", 1), { expanded: false, hiddenRings: [10] });
  assert.deepEqual(smartPrefs(v, "exp.run_a", 1), { expanded: true, hiddenRings: [] });
  assert.deepEqual(smartPrefs(v, "exp.run_b", 1), { expanded: false, hiddenRings: [] });
});

test("old unscoped keys are dropped silently", () => {
  assert.deepEqual(parseSmartView({ "3": { expanded: true, hiddenRings: [5] }, "live:3": { expanded: true, hiddenRings: [] }, "exp.20261021_x:2": { expanded: false, hiddenRings: [25] } }),
    { "live:3": { expanded: true, hiddenRings: [] }, "exp.20261021_x:2": { expanded: false, hiddenRings: [25] } });
});
