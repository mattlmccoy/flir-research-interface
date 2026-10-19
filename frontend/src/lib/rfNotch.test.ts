import { test } from "node:test";
import assert from "node:assert/strict";
import { rfNotchStatus } from "./rfNotch.ts";

test("the status line says what the RF-banding filter actually did, never just 'on'", () => {
  assert.equal(rfNotchStatus(false, undefined), null);
  assert.equal(rfNotchStatus(true, undefined), "waiting for filtered frames…");
  assert.equal(rfNotchStatus(true, { applied: false, reason: "not temperature-linear (raw counts)" }), "not available: not temperature-linear (raw counts)");
  assert.equal(rfNotchStatus(true, { applied: true, bands: [], rms_mk: 0, max_mk: 0 }), "no RF banding found");
  assert.equal(rfNotchStatus(true, { applied: true, bands: ["diag+", "diag-"], rms_mk: 773.9, max_mk: 2679.3 }), "removed RF banding · 774 mK rms (2 bands)");
  assert.equal(rfNotchStatus(true, { applied: true, bands: ["diag+"], rms_mk: 16.4, max_mk: 40 }), "removed RF banding · 16 mK rms (1 band)");
});
