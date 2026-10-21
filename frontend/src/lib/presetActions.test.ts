import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { NUC_WARNING, RECORDING_SKIP, type Preset, type ViewDisplay } from "./presets.ts";
import { applyLivePreset, applyLook, saveCurrentPreset, type LiveDeps } from "./presetActions.ts";

// the real A70 camera_info (backend/tests/fixtures, captured 2026-10-21): case 1, NUCMode Automatic
const A70 = JSON.parse(readFileSync(new URL("../../../backend/tests/fixtures/camera_info_a70_20261021.json", import.meta.url), "utf8")) as Record<string, unknown>;
const LOOK = { exposure_ev: -1, brightness: 0, contrast: 1.4 };
const BED: Preset = {
  name: "sintering bed",
  visible_adjust: LOOK,
  thermal: { ObjectEmissivity: 0.9, CurrentCase: 2, NUCMode: "Off" },
  display: { palette: "inferno", range: { mode: "locked", min_c: 20, max_c: 250 } },
};
const VIEW: ViewDisplay = { palette: "iron", scaleMode: "auto", manual: { min: 20, max: 40 } };

function deps(over: Partial<LiveDeps> = {}) {
  const log = { visible: [] as unknown[], view: [] as unknown[], writes: [] as Record<string, unknown>[], confirms: [] as string[], applied: [] as (string | null)[] };
  const d: LiveDeps = {
    recording: false, cameraConnected: true, view: VIEW,
    setVisible: (a) => log.visible.push(a), setView: (v) => log.view.push(v),
    readInfo: async () => A70,
    setParameters: async (v) => { log.writes.push(v); return { applied: v }; },
    confirm: (m) => { log.confirms.push(m); return true; },
    markApplied: async (n) => { log.applied.push(n); },
    ...over,
  };
  return { d, log };
}

test("live apply while recording sets the sliders and display, writes nothing to the camera and says so", async () => {
  const { d, log } = deps({ recording: true });
  const lines = await applyLivePreset(BED, d);
  assert.deepEqual(log.visible, [LOOK]);
  assert.deepEqual(log.view, [{ palette: "inferno", scaleMode: "manual", manual: { min: 20, max: 250 } }]);
  assert.deepEqual(log.writes, []);
  assert.deepEqual(log.confirms, []);
  assert.ok(lines.some((l) => l.warn && l.text === RECORDING_SKIP));
  assert.deepEqual(log.applied, ["sintering bed"]);
});

test("live apply asks first, warns about the NUC, and writes the changed nodes one by one, case last", async () => {
  const { d, log } = deps();
  const lines = await applyLivePreset(BED, d);
  assert.equal(log.confirms.length, 1);
  assert.match(log.confirms[0], new RegExp(NUC_WARNING));
  assert.deepEqual(log.writes, [{ ObjectEmissivity: 0.9 }, { NUCMode: "Off" }, { CurrentCase: 2 }]);
  assert.ok(lines.some((l) => !l.warn && /wrote ObjectEmissivity, NUCMode, CurrentCase/.test(l.text)));
});

test("live apply with the camera write cancelled writes nothing and says so", async () => {
  const { d, log } = deps({ confirm: () => false });
  const lines = await applyLivePreset(BED, d);
  assert.deepEqual(log.writes, []);
  assert.deepEqual(log.visible, [LOOK]);
  assert.ok(lines.some((l) => l.warn && /cancelled/.test(l.text)));
});

test("live apply reports which nodes were written when a write fails part-way", async () => {
  const { d } = deps({ setParameters: async (v) => { if ("NUCMode" in v) throw new Error("409 camera parameters are locked while recording"); return v; } });
  const lines = await applyLivePreset(BED, d);
  const bad = lines.find((l) => l.warn && /failed at NUCMode/.test(l.text));
  assert.ok(bad, JSON.stringify(lines));
  assert.match(bad.text, /written: ObjectEmissivity/);
  assert.match(bad.text, /not written: CurrentCase/);
});

test("live apply with unreadable camera info writes nothing", async () => {
  const { d, log } = deps({ readInfo: async () => { throw new Error("409 not connected"); } });
  const lines = await applyLivePreset(BED, d);
  assert.deepEqual(log.writes, []);
  assert.ok(lines.some((l) => l.warn && /camera settings not applied/.test(l.text)));
});

test("save current without a camera (409) stores the preset without camera settings and says so", async () => {
  const put: Preset[] = [];
  const msg = await saveCurrentPreset("bed", { visible: LOOK, view: VIEW, currentThermal: async () => { throw new Error("409 not connected"); }, put: async (p) => { put.push(p); } });
  assert.equal(put.length, 1);
  assert.deepEqual(put[0].thermal, {});
  assert.deepEqual(put[0].display, { palette: "iron", range: { mode: "auto" } });
  assert.match(msg, /without camera settings/);
});

test("save current lists the camera values it could not read", async () => {
  const put: Preset[] = [];
  const msg = await saveCurrentPreset("bed", { visible: LOOK, view: VIEW, currentThermal: async () => ({ thermal: { ObjectEmissivity: 0.95, ExtOpticsTemperature: null }, left_out: ["IRFrameRate"] }), put: async (p) => { put.push(p); } });
  assert.deepEqual(put[0].thermal, { ObjectEmissivity: 0.95 });
  assert.match(msg, /ExtOpticsTemperature, IRFrameRate/);
});

test("save current does not save when reading the camera fails for another reason", async () => {
  const put: Preset[] = [];
  await assert.rejects(saveCurrentPreset("bed", { visible: LOOK, view: VIEW, currentThermal: async () => { throw new Error("500 camera timeout"); }, put: async (p) => { put.push(p); } }), /500/);
  assert.equal(put.length, 0);
});

test("apply look sets the run's adjustment and the display, and has no camera path at all", () => {
  const set: unknown[] = [], views: unknown[] = [];
  const lines = applyLook(BED, { hasVideo: true, setAdjust: (a) => set.push(a), view: VIEW, setView: (v) => views.push(v) });
  assert.deepEqual(set, [LOOK]);
  assert.deepEqual(views, [{ palette: "inferno", scaleMode: "manual", manual: { min: 20, max: 250 } }]);
  assert.ok(lines.some((l) => /camera settings are not changed/.test(l.text)));
});

test("apply look on a run without visible video sets only the display", () => {
  const set: unknown[] = [];
  const lines = applyLook(BED, { hasVideo: false, setAdjust: (a) => set.push(a), view: VIEW, setView: () => undefined });
  assert.deepEqual(set, []);
  assert.ok(lines.some((l) => /no visible video/.test(l.text)));
});
