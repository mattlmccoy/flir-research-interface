import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MASKS,
  loadMasks,
  maskAt,
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
  s = maskReducer(s, { type: "add", shape: { kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2 } });
  s = maskReducer(s, { type: "add", shape: { kind: "polygon", points: [[0, 0], [3, 0], [0, 3]] } });
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
  s = maskReducer(EMPTY_MASKS, { type: "load", shapes: [{ id: 4, kind: "spot" }, rect(7, "include", 0, 0, 1, 1)] });
  assert.deepEqual(s.shapes.map((m) => m.id), [7]); // only rasterisable shapes survive a load
  assert.equal(s.nextId, 8);
});

test("maskAt finds the topmost shape under a pixel, for shift-click", () => {
  const shapes: MaskShape[] = [rect(1, "include", 0, 0, 6, 6), rect(2, "exclude", 2, 2, 4, 4)];
  assert.equal(maskAt(shapes, 3, 3, W, H), 2); // drawn last wins
  assert.equal(maskAt(shapes, 1, 1, W, H), 1);
  assert.equal(maskAt(shapes, 9, 7, W, H), null);
});

test("entering mask mode lands on a drawing tool, so the first drag draws a region", () => {
  assert.equal(toolForMaskMode("select"), "rect"); // select would only pick, never draw
  assert.equal(toolForMaskMode("spot"), "rect");
  assert.equal(toolForMaskMode("polygon"), "polygon");
  assert.equal(toolForMaskMode("freehand"), "freehand");
  assert.equal(toolForMaskMode("rect"), "rect");
});
