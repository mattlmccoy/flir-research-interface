import { test } from "node:test";
import assert from "node:assert/strict";
import { fmtAny, fmtCelsius, kelvinToCelsiusLabel } from "./format.ts";

test("fmtCelsius: null/undefined render as an em dash, a number gets toFixed(2) + unit", () => {
  assert.equal(fmtCelsius(null), "—");
  assert.equal(fmtCelsius(undefined), "—");
  assert.equal(fmtCelsius(12.345), "12.35 °C");
});

test("kelvinToCelsiusLabel: a number converts kelvin to celsius at one decimal, else an em dash", () => {
  assert.equal(kelvinToCelsiusLabel(293.15), "20.0 °C");
  assert.equal(kelvinToCelsiusLabel("not a number"), "—");
  assert.equal(kelvinToCelsiusLabel(undefined), "—");
  assert.equal(kelvinToCelsiusLabel(null), "—");
});

test("fmtAny: null/undefined render as an em dash, a number gets toFixed(2), anything else is stringified", () => {
  assert.equal(fmtAny(null), "—");
  assert.equal(fmtAny(undefined), "—");
  assert.equal(fmtAny(0.949999), "0.95");
  assert.equal(fmtAny("manual"), "manual");
});
