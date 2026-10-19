import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MASKS,
  loadMasks,
  maskAt,
  masksAsRois,
  maskField,
  maskPixels,
  maskReducer,
  maskedStats,
  saveMasks,
  toolForMaskMode,
  type MaskShape,
} from "./mask.ts";
import { autoScale } from "./scale.ts";

const W = 10, H = 8;
const rect = (id: number, mode: "include" | "exclude", x0: number, y0: number, x1: number, y1: number): MaskShape =>
  ({ id, kind: "rect", x0, y0, x1, y1, mode });
const count = (m: Uint8Array) => m.reduce((n, v) => n + v, 0);

function memStorage(): Storage {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => { m.set(k, v); }, removeItem: (k) => { m.delete(k); }, clear: () => m.clear(), key: () => null, get length() { return m.size; } };
}

test("no shapes means no mask: every pixel counts", () => {
  assert.equal(maskPixels([], W, H), null);
});

test("exclude-only masks use the whole frame minus the excluded regions", () => {
  const m = maskPixels([rect(1, "exclude", 0, 0, 4, 2)], W, H)!;
  assert.equal(count(m), W * H - 8);
  assert.equal(m[0], 0);
  assert.equal(m[W * H - 1], 1);
});

test("include regions minus exclude regions when any include region exists", () => {
  const m = maskPixels([rect(1, "include", 2, 2, 6, 6), rect(2, "exclude", 2, 2, 4, 4)], W, H)!;
  assert.equal(count(m), 16 - 4);
  assert.equal(m[2 * W + 2], 0); // excluded corner of the include region
  assert.equal(m[5 * W + 5], 1);
  assert.equal(m[0], 0); // outside every include region
});

test("polygon masks cover the same pixels as a polygon ROI", () => {
  const tri: MaskShape = { id: 1, kind: "polygon", points: [[0, 0], [6, 0], [0, 6]], mode: "include" };
  const m = maskPixels([tri], W, H)!;
  assert.equal(m[0], 1);
  assert.equal(m[7 * W + 9], 0);
});

test("maskField hides pixels outside the mask and leaves the input alone", () => {
  const c = new Float32Array(W * H).fill(20);
  const m = maskPixels([rect(1, "exclude", 0, 0, 1, 1)], W, H)!;
  const f = maskField(c, m);
  assert.ok(Number.isNaN(f[0]));
  assert.equal(f[1], 20);
  assert.equal(c[0], 20);
});

test("a hot excluded region no longer sets the auto colour range", () => {
  const c = new Float32Array(W * H);
  for (let i = 0; i < c.length; i++) c[i] = 20 + (i % 7) * 0.1; // cool, low-contrast scene
  for (let y = 0; y < 3; y++) for (let x = 7; x < 10; x++) c[y * W + x] = 300; // hot transformer
  const m = maskPixels([rect(1, "exclude", 7, 0, 10, 3)], W, H)!;
  const r = autoScale(maskField(c, m))!;
  assert.ok(r.max < 21, `range max ${r.max} should come from the scene, not the transformer`);
});

test("maskedStats summarise only masked, valid pixels", () => {
  const c = new Float32Array(W * H).fill(10);
  c[5] = NaN; // over-range pixel inside the mask
  c[W * H - 1] = 99; // outside the mask
  const m = maskPixels([rect(1, "include", 0, 0, W, 2)], W, H)!;
  const s = maskedStats(c, m)!;
  assert.deepEqual(s, { min: 10, max: 10, mean: 10, n: 2 * W - 1 });
  assert.equal(maskedStats(new Float32Array(W * H).fill(NaN), m), null);
});

test("new shapes take the draw mode; shift-click flips; remove and switch off keep the rest", () => {
  let s = maskReducer(EMPTY_MASKS, { type: "setDrawMode", mode: "exclude" });
  s = maskReducer(s, { type: "add", shape: { kind: "rect", x0: 0, y0: 0, x1: 5, y1: 5 } });
  s = maskReducer(s, { type: "add", shape: { kind: "polygon", points: [[0, 0], [6, 0], [0, 6]] } });
  assert.deepEqual(s.shapes.map((m) => [m.id, m.mode]), [[1, "exclude"], [2, "exclude"]]);
  s = maskReducer(s, { type: "toggleMode", id: 2 });
  assert.equal(s.shapes[1].mode, "include");
  s = maskReducer(s, { type: "remove", id: 1 });
  assert.deepEqual(s.shapes.map((m) => m.id), [2]);
  s = maskReducer(s, { type: "setEnabled", enabled: false });
  assert.equal(s.enabled, false);
  assert.equal(s.shapes.length, 1);
});

test("masks persist per scope and malformed storage falls back to none", () => {
  const st = memStorage();
  let s = maskReducer(EMPTY_MASKS, { type: "add", shape: { kind: "rect", x0: 1, y0: 1, x1: 3, y1: 3 } });
  saveMasks(st, s, "exp.run1");
  assert.deepEqual(loadMasks(st, "exp.run1").shapes, s.shapes);
  assert.deepEqual(loadMasks(st, "live").shapes, []);
  st.setItem("flir.masks.v1.live", "{nope");
  assert.deepEqual(loadMasks(st, "live"), EMPTY_MASKS);
  s = maskReducer(EMPTY_MASKS, { type: "load", shapes: [{ id: 4, kind: "spot" }, rect(7, "include", 0, 0, 4, 4)] });
  assert.deepEqual(s.shapes.map((m) => m.id), [7]); // only rasterisable shapes survive a load
  assert.equal(s.nextId, 8);
});

test("maskAt finds the topmost shape under a pixel, for shift-click", () => {
  const shapes: MaskShape[] = [rect(1, "include", 0, 0, 6, 6), rect(2, "exclude", 2, 2, 4, 4)];
  assert.equal(maskAt(shapes, 3, 3, W, H), 2); // drawn last wins
  assert.equal(maskAt(shapes, 1, 1, W, H), 1);
  assert.equal(maskAt(shapes, 9, 7, W, H), null);
});

test("entering mask mode keeps the selector (and any mask drawing tool); other tools become the selector", () => {
  assert.equal(toolForMaskMode("select"), "select");
  assert.equal(toolForMaskMode("spot"), "select");
  assert.equal(toolForMaskMode("circle"), "select");
  assert.equal(toolForMaskMode("polygon"), "polygon");
  assert.equal(toolForMaskMode("freehand"), "freehand");
  assert.equal(toolForMaskMode("rect"), "rect");
});

test("in mask mode the ROI editing actions select, move, reshape and delete mask regions", () => {
  let s = maskReducer(EMPTY_MASKS, { type: "setDrawMode", mode: "exclude" });
  s = maskReducer(s, { type: "add", shape: { kind: "rect", x0: 10, y0: 10, x1: 20, y1: 20 } });
  s = maskReducer(s, { type: "setDrawMode", mode: "include" });
  s = maskReducer(s, { type: "add", shape: { kind: "polygon", points: [[0, 0], [8, 0], [0, 8]] } });
  s = maskReducer(s, { type: "edit", action: { type: "select", id: 1 } });
  assert.equal(s.selected, 1);
  s = maskReducer(s, { type: "edit", action: { type: "move", id: 1, dx: 5, dy: -3 } });
  assert.deepEqual(s.shapes[0], { id: 1, kind: "rect", x0: 15, y0: 7, x1: 25, y1: 17, mode: "exclude" });
  s = maskReducer(s, { type: "edit", action: { type: "setVertex", id: 2, index: 1, x: 12, y: 1 } });
  assert.deepEqual(s.shapes[1], { id: 2, kind: "polygon", points: [[0, 0], [12, 1], [0, 8]], mode: "include" });
  s = maskReducer(s, { type: "edit", action: { type: "remove", id: 1 } });
  assert.deepEqual(s.shapes.map((m) => m.id), [2]);
  assert.equal(s.selected, null);
});

test("mask regions are shown to the editing layer as labelled, mode-coloured ROIs", () => {
  const shapes: MaskShape[] = [rect(1, "exclude", 0, 0, 4, 4), { id: 2, kind: "polygon", points: [[0, 0], [5, 0], [0, 5]], mode: "include" }];
  const rois = masksAsRois(shapes);
  assert.deepEqual(rois.map((r) => [r.id, r.kind, r.name]), [[1, "rect", "exclude 1"], [2, "polygon", "include 2"]]);
  assert.notEqual(rois[0].color, rois[1].color);
});

test("new regions are include by default (draw the area you want to see)", () => {
  const s = maskReducer(EMPTY_MASKS, { type: "add", shape: { kind: "rect", x0: 0, y0: 0, x1: 10, y1: 10 } });
  assert.equal(s.shapes[0].mode, "include");
});

test("a click without a drag makes no region, and stray specks are dropped on load", () => {
  const speck = { kind: "rect" as const, x0: 5, y0: 5, x1: 6, y1: 6 };
  assert.equal(maskReducer(EMPTY_MASKS, { type: "add", shape: speck }).shapes.length, 0);
  const sliver: MaskShape = { id: 3, kind: "polygon", points: [[0, 0], [1, 0], [0, 1]], mode: "exclude" };
  const s = maskReducer(EMPTY_MASKS, { type: "load", shapes: [{ ...speck, id: 2, mode: "exclude" }, sliver, rect(4, "include", 0, 0, 10, 10)] });
  assert.deepEqual(s.shapes.map((m) => m.id), [4]);
});

test("the include/exclude choice is not remembered between sessions", () => {
  const st = memStorage();
  saveMasks(st, maskReducer(EMPTY_MASKS, { type: "setDrawMode", mode: "exclude" }), "live");
  assert.equal(loadMasks(st, "live").drawMode, "include");
});
