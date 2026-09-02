import { test } from "node:test";
import assert from "node:assert/strict";
import { formFromInfo, valuesFromForm, type CameraForm } from "./camera.ts";

const INFO = {
  active_case: { index: 1, low_c: -20, high_c: 250 },
  measurement_cases: [{ index: 0, low_c: -20, high_c: 175 }, { index: 1, low_c: -20, high_c: 250 }, { index: 2, low_c: 175, high_c: 1000 }],
  object_parameters: { ObjectEmissivity: 0.95, ReflectedTemperature: 293.15, AtmosphericTemperature: 293.15, ObjectDistance: 1, RelativeHumidity: 0.5 },
  nuc_mode: "Automatic",
  ir_frame_rate: "Rate30Hz",
  enum_options: { NUCMode: ["Off", "Automatic"], IRFrameRate: ["Rate60Hz", "Rate30Hz"] },
};

test("formFromInfo converts Kelvin to °C and fractions to percent", () => {
  const f = formFromInfo(INFO);
  assert.equal(f.emissivity, 0.95);
  assert.ok(Math.abs((f.reflected_c as number) - 20) < 1e-9);
  assert.ok(Math.abs((f.atmospheric_c as number) - 20) < 1e-9);
  assert.equal(f.distance_m, 1);
  assert.equal(f.humidity_pct, 50);
  assert.equal(f.case_index, 1);
  assert.equal(f.nuc_mode, "Automatic");
  assert.equal(f.ir_frame_rate, "Rate30Hz");
});

test("formFromInfo tolerates missing fields (older backends) with nulls", () => {
  const f = formFromInfo({});
  assert.equal(f.emissivity, null);
  assert.equal(f.case_index, null);
  assert.equal(f.nuc_mode, null);
});

test("valuesFromForm emits only changed nodes, in camera units", () => {
  const base = formFromInfo(INFO);
  const edited: CameraForm = { ...base, emissivity: 0.9, reflected_c: 22.5, humidity_pct: 40, case_index: 2, nuc_mode: "Off" };
  const v = valuesFromForm(edited, base);
  assert.deepEqual(Object.keys(v).sort(), ["CurrentCase", "NUCMode", "ObjectEmissivity", "ReflectedTemperature", "RelativeHumidity"]);
  assert.equal(v.ObjectEmissivity, 0.9);
  assert.ok(Math.abs((v.ReflectedTemperature as number) - 295.65) < 1e-9);
  assert.equal(v.RelativeHumidity, 0.4);
  assert.equal(v.CurrentCase, 2);
  assert.equal(v.NUCMode, "Off");
  assert.deepEqual(valuesFromForm(base, base), {});
});

test("valuesFromForm skips null (unknown) fields", () => {
  const base = formFromInfo({});
  assert.deepEqual(valuesFromForm({ ...base, emissivity: 0.8 }, base), { ObjectEmissivity: 0.8 });
});
