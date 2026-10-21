import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  NUC_WARNING,
  applyPlan,
  displayFromView,
  isModified,
  presetFromState,
  thermalFromInfo,
  viewFromDisplay,
  writeThermal,
  type Preset,
  type ViewDisplay,
} from "./presets.ts";

// camera_info() of the real A70 (captured 2026-10-21, backend/tests/fixtures): float32 node values
// (emissivity 0.949999988…), enum_options from the camera, active case index 1.
const A70 = JSON.parse(readFileSync(new URL("../../../backend/tests/fixtures/camera_info_a70_20261021.json", import.meta.url), "utf8")) as Record<string, unknown>;
const A70_ENUMS = A70.enum_options as Record<string, string[]>;
const A70_NOW = thermalFromInfo(A70).values;

const LOOK = { exposure_ev: -1, brightness: 0, contrast: 1.4 };
const BED: Preset = {
  name: "sintering bed",
  visible_adjust: LOOK,
  thermal: { ObjectEmissivity: 0.9, ObjectDistance: 0.457, CurrentCase: 2, NUCMode: "Off", IRFrameRate: "Rate30Hz" },
  display: { palette: "inferno", range: { mode: "locked", min_c: 20, max_c: 250 } },
};
const LIVE = { recording: false, cameraConnected: true, enumOptions: A70_ENUMS, current: A70_NOW };

test("thermalFromInfo reads the writable nodes of a real A70 camera_info, as the backend does", () => {
  const { values, leftOut } = thermalFromInfo(A70);
  assert.deepEqual(Object.keys(values), [
    "ObjectEmissivity", "ReflectedTemperature", "AtmosphericTemperature", "ObjectDistance", "RelativeHumidity",
    "ExtOpticsTemperature", "ExtOpticsTransmission", "CurrentCase", "NUCMode", "IRFrameRate",
  ]);
  assert.equal(values.CurrentCase, 1);
  assert.equal(values.NUCMode, "Automatic");
  assert.equal(values.IRFrameRate, "Rate30Hz");
  assert.equal(values.ObjectEmissivity, 0.949999988079071);
  assert.deepEqual(leftOut, []);
  assert.equal("EstimatedTransmission" in values, false);
});

test("applyPlan while recording skips thermal but keeps visible and display, with a message", () => {
  const plan = applyPlan(BED, { ...LIVE, recording: true });
  assert.equal(plan.thermal, null);
  assert.deepEqual(plan.visible, LOOK);
  assert.deepEqual(plan.display, BED.display);
  assert.ok(plan.warnings.some((w) => /recording/.test(w) && /camera settings/.test(w)), plan.warnings.join(" | "));
});

test("applyPlan without a camera skips thermal with a message", () => {
  const plan = applyPlan(BED, { ...LIVE, cameraConnected: false });
  assert.equal(plan.thermal, null);
  assert.deepEqual(plan.visible, LOOK);
  assert.ok(plan.warnings.some((w) => /no camera/.test(w)), plan.warnings.join(" | "));
});

test("applyPlan writes CurrentCase last and warns that it triggers a NUC", () => {
  const plan = applyPlan(BED, LIVE);
  assert.ok(plan.thermal);
  const names = plan.thermal.map(([n]) => n);
  assert.equal(names[names.length - 1], "CurrentCase");
  assert.deepEqual(plan.thermal[plan.thermal.length - 1], ["CurrentCase", 2]);
  assert.ok(plan.warnings.includes(NUC_WARNING));
});

test("applyPlan leaves out values the camera already has (float32 round-off counts as equal)", () => {
  // 0.457 vs the camera's 0.4569999873638153, Rate30Hz vs Rate30Hz: unchanged
  const plan = applyPlan(BED, LIVE);
  assert.deepEqual(plan.thermal, [["ObjectEmissivity", 0.9], ["NUCMode", "Off"], ["CurrentCase", 2]]);
  const same = applyPlan({ ...BED, thermal: { ...A70_NOW, ObjectEmissivity: 0.95 } }, LIVE);
  assert.deepEqual(same.thermal, []);
  assert.equal(same.warnings.includes(NUC_WARNING), false, "an unchanged case does not warn");
});

test("applyPlan reports an enum value the camera does not offer in skipped and does not write it", () => {
  const plan = applyPlan({ ...BED, thermal: { IRFrameRate: "Rate9Hz", NUCMode: "Off" } }, LIVE);
  assert.deepEqual(plan.skipped, ["IRFrameRate"]);
  assert.deepEqual(plan.thermal, [["NUCMode", "Off"]]);
  assert.ok(plan.warnings.some((w) => /IRFrameRate/.test(w) && /Rate9Hz/.test(w)));
});

test("applyPlan skips a node that is not a writable camera parameter", () => {
  const plan = applyPlan({ ...BED, thermal: { Gain: 3 } as Record<string, number> }, LIVE);
  assert.deepEqual(plan.skipped, ["Gain"]);
  assert.deepEqual(plan.thermal, []);
});

test("applyPlan of a preset without camera settings while recording says nothing about them", () => {
  const plan = applyPlan({ ...BED, thermal: {} }, { ...LIVE, recording: true });
  assert.equal(plan.thermal, null);
  assert.deepEqual(plan.warnings, []);
});

test("P1 mapping: auto ↔ ScaleMode auto, locked ↔ manual min/max", () => {
  const view: ViewDisplay = { palette: "iron", scaleMode: "manual", manual: { min: 20, max: 250 } };
  assert.deepEqual(displayFromView(view), { palette: "iron", range: { mode: "locked", min_c: 20, max_c: 250 } });
  assert.deepEqual(displayFromView({ ...view, scaleMode: "auto" }), { palette: "iron", range: { mode: "auto" } });
  assert.deepEqual(displayFromView({ ...view, manual: { min: 250, max: 20 } }).range, { mode: "locked", min_c: 20, max_c: 250 });
  const cur: ViewDisplay = { palette: "iron", scaleMode: "auto", manual: { min: 0, max: 50 } };
  assert.deepEqual(viewFromDisplay({ palette: "inferno", range: { mode: "locked", min_c: 20, max_c: 250 } }, cur).view,
    { palette: "inferno", scaleMode: "manual", manual: { min: 20, max: 250 } });
  assert.deepEqual(viewFromDisplay({ palette: "inferno", range: { mode: "auto" } }, cur).view,
    { palette: "inferno", scaleMode: "auto", manual: { min: 0, max: 50 } }, "auto keeps the manual range for later");
});

test("viewFromDisplay keeps the current palette for one this UI does not have, and says so", () => {
  const cur: ViewDisplay = { palette: "iron", scaleMode: "auto", manual: { min: 0, max: 50 } };
  const r = viewFromDisplay({ palette: "hotmetal", range: { mode: "auto" } }, cur);
  assert.equal(r.view.palette, "iron");
  assert.ok(r.warnings.some((w) => /hotmetal/.test(w)));
});

test("isModified is false right after applying and true once a slider, the palette or the range moves", () => {
  const disp = BED.display;
  assert.equal(isModified({ visible: { ...LOOK }, display: disp }, BED), false);
  assert.equal(isModified({ visible: { ...LOOK, contrast: 1.5 }, display: disp }, BED), true);
  assert.equal(isModified({ visible: { ...LOOK }, display: { ...disp, palette: "iron" } }, BED), true);
  assert.equal(isModified({ visible: { ...LOOK }, display: { ...disp, range: { mode: "auto" } } }, BED), true);
  assert.equal(isModified({ visible: { ...LOOK }, display: { ...disp, range: { mode: "locked", min_c: 20, max_c: 251 } } }, BED), true);
});

test("isModified compares the camera settings only when they are known", () => {
  const cur = { visible: { ...LOOK }, display: BED.display };
  assert.equal(isModified({ ...cur, thermal: null }, BED), false);
  assert.equal(isModified({ ...cur, thermal: A70_NOW }, BED), true, "the A70 has emissivity 0.95, the preset 0.9");
  const matching = { ...A70_NOW, ObjectEmissivity: 0.9000000357627869, NUCMode: "Off", CurrentCase: 2 };
  assert.equal(isModified({ ...cur, thermal: matching }, BED), false);
});

test("presetFromState excludes null thermal values and lists them with the ones already left out", () => {
  const view: ViewDisplay = { palette: "iron", scaleMode: "manual", manual: { min: 20, max: 40 } };
  const { preset, omitted } = presetFromState("  white powder ", LOOK, displayFromView(view),
    { ObjectEmissivity: 0.95, ExtOpticsTemperature: null, NUCMode: "Automatic" }, ["IRFrameRate"]);
  assert.deepEqual(preset, {
    name: "white powder",
    visible_adjust: LOOK,
    thermal: { ObjectEmissivity: 0.95, NUCMode: "Automatic" },
    display: { palette: "iron", range: { mode: "locked", min_c: 20, max_c: 40 } },
  });
  assert.deepEqual(omitted, ["ExtOpticsTemperature", "IRFrameRate"]);
});

test("presetFromState with no camera stores no thermal block", () => {
  const { preset, omitted } = presetFromState("x", LOOK, { palette: "iron", range: { mode: "auto" } }, null, []);
  assert.deepEqual(preset.thermal, {});
  assert.deepEqual(omitted, []);
});

test("writeThermal writes one node at a time in order and reports a failure part-way", async () => {
  const sent: Record<string, unknown>[] = [];
  const set = async (v: Record<string, unknown>) => {
    sent.push(v);
    if ("NUCMode" in v) throw new Error("500 camera rejected the write");
    return { applied: v };
  };
  const r = await writeThermal([["ObjectEmissivity", 0.9], ["NUCMode", "Off"], ["CurrentCase", 2]], set);
  assert.deepEqual(sent, [{ ObjectEmissivity: 0.9 }, { NUCMode: "Off" }]);
  assert.deepEqual(r.written, ["ObjectEmissivity"]);
  assert.deepEqual(r.failed, { node: "NUCMode", error: "Error: 500 camera rejected the write" });
  assert.deepEqual(r.notWritten, ["CurrentCase"]);
});

test("writeThermal with every write accepted reports them all", async () => {
  const r = await writeThermal([["ObjectEmissivity", 0.9], ["CurrentCase", 2]], async (v) => ({ applied: v }));
  assert.deepEqual(r, { written: ["ObjectEmissivity", "CurrentCase"], failed: null, notWritten: [] });
});
