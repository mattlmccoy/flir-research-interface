import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseSmartSeries, type SmartSeries } from "./smartSeries.ts";
import { smartTraces } from "./smartTraces.ts";

// Captured from the real API (GET /api/experiments/{name}/smart-roi/3) on a recording built from the
// five real A70 frames of 20261020_144402_Run (scripts/capture_smart_series_fixture.py):
// rows 0 and 36–45 searching, 1–5 and 46–47 locked, 6–35 holding; rings 0–5, 5–10, 10–25 px.
const RAW: unknown = JSON.parse(readFileSync(new URL("./fixtures/smart_series_20261020.json", import.meta.url), "utf8"));
const series = (): SmartSeries => {
  const s = parseSmartSeries(RAW);
  assert.ok(s, "the captured payload parses");
  return s;
};
const ROI = { id: 3, label: "graphite", color: "var(--trace-1)" };
const ALL = { sample: true, rings: true, dims: "off" as const };

test("sample mean on the °C axis is the ROI's own trace (id = ROI id, ROI colour, solid)", () => {
  const [tr] = smartTraces(series(), { sample: true, rings: false, dims: "off" }, ROI);
  assert.equal(tr.id, 3);
  assert.equal(tr.axis, "temp");
  assert.equal(tr.color, ROI.color);
  assert.equal(tr.dash, undefined);
  assert.equal(tr.label, "graphite mean");
  assert.deepEqual(Array.from(tr.t), series().t_s);
  assert.ok(Math.abs(tr.v[5] - 113.36285751753641) < 1e-9);
});

test("searching rows are gaps (NaN) on every trace, never 0; holding rows keep their values", () => {
  const s = series();
  for (const tr of smartTraces(s, { sample: true, rings: true, dims: "area" }, ROI)) {
    for (const i of [0, 36, 40, 45]) assert.ok(Number.isNaN(tr.v[i]), `${tr.label} row ${i} should be a gap`);
    assert.ok(Number.isFinite(tr.v[10]), `${tr.label} holding row is valid`);
    assert.ok(Number.isFinite(tr.v[46]), `${tr.label} re-locked row`);
  }
});

test("a searching row is a gap even if the payload carried a number there", () => {
  const s = series();
  const forged: SmartSeries = { ...s, sample: { ...s.sample, mean: s.sample.mean.map((v, i) => (i === 0 ? 0 : v)) } };
  const [tr] = smartTraces(forged, { sample: true, rings: false, dims: "off" }, ROI);
  assert.ok(Number.isNaN(tr.v[0]));
});

test("one dashed trace per stored ring band, labelled with the band", () => {
  const rings = smartTraces(series(), { sample: false, rings: true, dims: "off" }, ROI);
  assert.equal(rings.length, 3);
  assert.deepEqual(rings.map((r) => r.label), ["graphite ring 0–5 px mean", "graphite ring 5–10 px mean", "graphite ring 10–25 px mean"]);
  assert.ok(rings.every((r) => r.axis === "temp" && r.color === ROI.color && r.dash && r.dash.length > 0));
  assert.equal(new Set(rings.map((r) => r.id)).size, 3);
  assert.ok(rings.every((r) => r.id !== 3));
  assert.ok(Math.abs(rings[2].v[5] - 33.73849322965674) < 1e-9);
});

test("ring count follows the stored series (no rings → no ring traces)", () => {
  const s = series();
  assert.equal(smartTraces({ ...s, rings: s.rings.slice(0, 1) }, ALL, ROI).length, 2);
  assert.equal(smartTraces({ ...s, rings: [] }, ALL, ROI).length, 1);
});

test("dims choice picks that column, in px, on the size axis", () => {
  const s = series();
  const pick = (dims: "area" | "length" | "width") => smartTraces(s, { sample: false, rings: false, dims }, ROI);
  const [area] = pick("area"), [length] = pick("length"), [width] = pick("width");
  assert.equal(area.axis, "size");
  assert.equal(area.label, "graphite area (px)");
  assert.equal(area.v[1], 903);
  assert.ok(Math.abs(length.v[1] - 38.3192212476371) < 1e-9);
  assert.equal(width.v[1], s.dims.width_px[1]);
  assert.equal(width.label, "graphite width (px)");
  assert.equal(smartTraces(s, { sample: false, rings: false, dims: "off" }, ROI).length, 0);
});

test("nothing chosen, nothing drawn", () => {
  assert.deepEqual(smartTraces(series(), { sample: false, rings: false, dims: "off" }, ROI), []);
});
