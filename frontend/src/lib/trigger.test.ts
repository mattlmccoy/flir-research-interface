import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_TRIGGER_FORM, triggerFromForm, triggerSummary } from "./trigger.ts";

test("triggerFromForm builds the operator's trigger object and drops irrelevant fields", () => {
  const t = triggerFromForm({ ...DEFAULT_TRIGGER_FORM, startKind: "threshold", roi: 3, stat: "max", level: 80, direction: "rising", endKind: "duration", seconds: 90, pretrigger: 2 });
  assert.deepEqual(t, { start: { kind: "threshold", roi: 3, stat: "max", level_c: 80, direction: "rising", sustain_frames: 3 }, end: { kind: "duration", seconds: 90 }, pretrigger_s: 2, max_seconds: 1800 });
  const m = triggerFromForm({ ...DEFAULT_TRIGGER_FORM, startKind: "after", afterS: 5, endKind: "frames", frames: 300 });
  assert.deepEqual(m.start, { kind: "after", after_s: 5 });
  assert.deepEqual(m.end, { kind: "frames", frames: 300 });
});

test("triggerSummary is a readable one-liner", () => {
  const s = triggerSummary({ start: { kind: "threshold", roi: 3, stat: "max", level_c: 80, direction: "rising", sustain_frames: 3 }, end: { kind: "duration", seconds: 90 }, pretrigger_s: 2, max_seconds: 1800 });
  assert.equal(s, "start when ROI 3 max rises above 80 °C (3 frames) · stop after 90 s · 2 s pre-trigger · cap 1800 s");
  assert.equal(triggerSummary({ start: { kind: "manual" }, end: { kind: "manual" }, pretrigger_s: 0, max_seconds: 60 }), "start manually · stop manually · cap 60 s");
});
