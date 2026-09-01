import { test } from "node:test";
import assert from "node:assert/strict";
import { countsToCelsius } from "./radiometry.ts";

test("10 mK counts decode to celsius via kelvin offset", () => {
  const counts = new Uint16Array([29815, 47315, 50000]);
  const c = countsToCelsius(counts, 0.01, 273.15);
  assert.ok(Math.abs(c[0] - 25.0) < 0.011);
  assert.ok(Math.abs(c[1] - 200.0) < 0.011);
  assert.ok(Math.abs(c[2] - 226.85) < 0.011);
});

test("null scale yields NaN (no conversion rule)", () => {
  const c = countsToCelsius(new Uint16Array([1, 2]), null, 273.15);
  assert.ok(Number.isNaN(c[0]) && Number.isNaN(c[1]));
});
