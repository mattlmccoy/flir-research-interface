import { test } from "node:test";
import assert from "node:assert/strict";
import { rightAxis, rightAxisOptions } from "./controlOverlay.ts";

const t_s = [0, 1, 2];
const rf = { t_s, forward_w: [100, null, 250] };
const caps = { t_s, tune_cap_percent: [41.5, null, 41.5], load_cap_percent: [63, 70.25, 70.25] };

test("options list only what the run actually recorded", () => {
  assert.deepEqual(rightAxisOptions(null), []);
  assert.deepEqual(rightAxisOptions(rf), ["rf"]);
  assert.deepEqual(rightAxisOptions({ ...rf, ...caps }), ["rf", "caps"]);
  assert.deepEqual(rightAxisOptions(caps), ["caps"]);
  // a cap column that is present but all-null (older TC-POWER) is not offered
  assert.deepEqual(rightAxisOptions({ t_s, forward_w: [1, 2, 3], load_cap_percent: [null, null, null] }), ["rf"]);
});

test("rf mode: RF power in W; gaps are NaN, never zero", () => {
  const r = rightAxis({ ...rf, ...caps }, "rf");
  assert.equal(r.units, "W");
  assert.deepEqual(r.traces.map((x) => x.label), ["RF power"]);
  assert.ok(Number.isNaN(r.traces[0].v[1]));
});

test("caps mode: tune and load on one % axis, each its own line", () => {
  const r = rightAxis({ ...rf, ...caps }, "caps");
  assert.equal(r.units, "%");
  assert.deepEqual(r.traces.map((x) => x.label), ["tune cap", "load cap"]);
  assert.notEqual(r.traces[0].color, r.traces[1].color);
  assert.ok(Number.isNaN(r.traces[0].v[1]));
  assert.deepEqual(r.traces[1].v, [63, 70.25, 70.25]);
});

test("off, or a mode the run lacks, draws nothing", () => {
  assert.deepEqual(rightAxis({ ...rf, ...caps }, "off").traces, []);
  assert.deepEqual(rightAxis(rf, "caps").traces, []);
  assert.deepEqual(rightAxis(null, "rf").traces, []);
});

test("cap lines never reuse an ROI trace color (they share the plot with the ROI temperatures)", async () => {
  const { TRACE_TOKENS } = await import("./overlay.ts");
  const roiColors = new Set(TRACE_TOKENS.map((t) => `var(${t})`));
  for (const tr of rightAxis({ ...rf, ...caps }, "caps").traces) {
    assert.ok(!roiColors.has(tr.color), `${tr.label} uses ROI color ${tr.color}`);
  }
});
