import { test } from "node:test";
import assert from "node:assert/strict";
import { snapshotFilename, snapshotFooter } from "./snapshot.ts";

test("snapshot filename is safe and carries the run, frame and time", () => {
  assert.equal(snapshotFilename("20260902_161239_AIT run/1", 41, 1.333), "20260902_161239_AIT_run_1_f0042_t1.333s.png");
  assert.equal(snapshotFilename("live", null, null), "live.png");
});

test("snapshot footer lists run, time, palette range and the ROI count", () => {
  const f = snapshotFooter({ name: "run7", tS: 12.5, index: 374, range: { min: 16.6, max: 22.7 }, palette: "iron", rois: 6, reference: false });
  assert.equal(f, "run7 · frame 375 · 12.500 s · iron 16.6–22.7 °C · 6 ROIs");
  const g = snapshotFooter({ name: "run7", tS: null, index: null, range: { min: -1, max: 1 }, palette: "iron", rois: 0, reference: true });
  assert.equal(g, "run7 · frame − reference ±1.0 °C");
});
