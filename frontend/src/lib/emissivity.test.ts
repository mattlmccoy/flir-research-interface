import { test } from "node:test";
import assert from "node:assert/strict";
import { radiance, temperatureK, recorrectCelsius, type Radiometry } from "./emissivity.ts";
import { roiStats } from "./roi.ts";

const RBF: Radiometry = { R: 22474.880859375, B: 1520, F: 1.0499999523162842, epsCam: 0.95, treflCamK: 293.15 };

test("radiance/temperature are inverses; same parameters is the identity", () => {
  for (const t of [250, 293.15, 350, 500]) assert.ok(Math.abs(temperatureK(radiance(t, RBF), RBF) - t) < 1e-6);
  assert.ok(Math.abs(recorrectCelsius(60, RBF, 0.95, 293.15) - 60) < 1e-4);
});

test("lower emissivity raises the estimate; NaN passes through; matches the backend reference", () => {
  const hot = recorrectCelsius(40, RBF, 0.3, 293.15);
  assert.ok(hot > 45);
  assert.ok(Number.isNaN(recorrectCelsius(NaN, RBF, 0.3, 293.15)));
  // true object 60 °C at eps 0.5, camera set to eps 0.95 / Trefl 20 °C: recover 60 from the reported value
  const wMeas = 0.5 * radiance(333.15, RBF) + 0.5 * radiance(293.15, RBF);
  const reported = temperatureK((wMeas - 0.05 * radiance(293.15, RBF)) / 0.95, RBF) - 273.15;
  assert.ok(Math.abs(recorrectCelsius(reported, RBF, 0.5, 293.15) - 60) < 1e-3);
});

test("roiStats applies the ROI's emissivity when radiometry is given", () => {
  const field = new Float32Array([60, 60, 60, 60]);
  const plain = roiStats(field, 2, 2, { id: 1, kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2 }, RBF);
  const corrected = roiStats(field, 2, 2, { id: 2, kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2, emissivity: 0.5 }, RBF);
  assert.ok(Math.abs((plain.mean ?? NaN) - 60) < 1e-4);
  assert.ok((corrected.mean ?? 0) > 70 && corrected.min === corrected.max, `corrected ${JSON.stringify(corrected)}`);
  const noRad = roiStats(field, 2, 2, { id: 2, kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2, emissivity: 0.5 });
  assert.ok(Math.abs((noRad.mean ?? NaN) - 60) < 1e-4, "without camera constants the raw value is kept");
});
