import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtTemp, convertTemp, UNIT_LABEL } from "./units.ts";

test("convertTemp / fmtTemp: °C, K, °F and raw counts (temperature-linear 10 mK)", () => {
  assert.equal(convertTemp(25, "C", null), 25);
  assert.ok(Math.abs(convertTemp(25, "K", null) - 298.15) < 1e-9);
  assert.equal(convertTemp(100, "F", null), 212);
  assert.equal(convertTemp(25, "counts", { kelvin_per_count: 0.01, kelvin_offset: 273.15 }), 29815);
  assert.equal(fmtTemp(25.123, "C", null), "25.12 °C");
  assert.equal(fmtTemp(25.123, "K", null), "298.27 K");
  assert.equal(fmtTemp(25, "counts", { kelvin_per_count: 0.01, kelvin_offset: 273.15 }), "29815");
  assert.equal(fmtTemp(NaN, "C", null), "n/a");
  assert.equal(UNIT_LABEL.F, "°F");
});
