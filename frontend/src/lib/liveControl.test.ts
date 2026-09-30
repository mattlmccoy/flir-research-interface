import { test } from "node:test";
import assert from "node:assert/strict";
import { LiveControl } from "./liveControl.ts";
import type { ControlStatus } from "./api.ts";

const st = (ctlTs: string, w: number | null, sp: number | null, rf: { ts: string; state: string } | null = null): ControlStatus => ({
  engaged: true,
  control_last: { ts: ctlTs, forward_w: w ?? undefined, setpoint_c: sp ?? undefined },
  rf_link_last_event: rf ? { ...rf, reason: null, forward_w: null } : null,
});

test("each new control sample is placed once at the live time it was seen", () => {
  const lc = new LiveControl();
  assert.equal(lc.ingest(st("old", 370, 150), 0), false, "the sample current at page open is history");
  assert.equal(lc.ingest(st("a", 100, 150), 1), true);
  assert.equal(lc.ingest(st("a", 100, 150), 2), false, "same sample polled again is not duplicated");
  lc.ingest(st("b", 250, 150), 3);
  const [rf] = lc.rightTraces();
  assert.deepEqual(Array.from(rf.t), [1, 3]);
  assert.deepEqual(Array.from(rf.v), [100, 250]);
  assert.equal(lc.leftTraces()[0].label, "setpoint");
});

test("no power or setpoint yet: no traces; manual mode (no setpoint) draws RF only", () => {
  const lc = new LiveControl();
  assert.deepEqual(lc.rightTraces(), []);
  lc.ingest(st("z", 1, null), 0);
  lc.ingest(st("a", 80, null), 1);
  assert.equal(lc.rightTraces().length, 1);
  assert.deepEqual(lc.leftTraces(), []);
});

test("RF edges become live markers, but not the edge already current when the page opened", () => {
  const lc = new LiveControl();
  lc.ingest(st("a", 0, null, { ts: "t0", state: "off" }), 0);  // both current at open: history
  assert.deepEqual(lc.markers, []);
  lc.ingest(st("a", 0, null, { ts: "t1", state: "on" }), 5);
  lc.ingest(st("a", 0, null, { ts: "t2", state: "off" }), 9);
  assert.deepEqual(lc.markers, [{ t: 5, label: "RF ON" }, { t: 9, label: "RF OFF" }]);
  lc.clear();
  assert.deepEqual(lc.markers, []);
  assert.deepEqual(lc.rightTraces(), []);
});
