import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeRect,
  roiLabel,
  roiReducer,
  roiStats,
  loadRois,
  saveRois,
  type Roi,
  type RoiState,
} from "./roi.ts";

const EMPTY: RoiState = { rois: [], selected: null, nextId: 1 };

// 4x3 field, row-major, x = column, y = row.
//   row 0: 10 11 12 13
//   row 1: 20 21 22 23
//   row 2: 30 31 NaN 33
const FIELD = new Float32Array([10, 11, 12, 13, 20, 21, 22, 23, 30, 31, NaN, 33]);
const W = 4;
const H = 3;

test("roiReducer add assigns sequential ids and selects the new roi", () => {
  const s1 = roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 2 } });
  assert.equal(s1.rois.length, 1);
  assert.equal(s1.rois[0].id, 1);
  assert.equal(s1.selected, 1);
  assert.equal(s1.nextId, 2);
  const s2 = roiReducer(s1, { type: "add", roi: { kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2 } });
  assert.deepEqual(s2.rois.map((r) => r.id), [1, 2]);
  assert.equal(s2.selected, 2);
  // input state not mutated
  assert.equal(EMPTY.rois.length, 0);
});

test("roiReducer remove drops the roi and clears selection only if it was selected", () => {
  const s = roiReducer(roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 2 } }), { type: "add", roi: { kind: "spot", x: 0, y: 0 } });
  const s2 = roiReducer(s, { type: "remove", id: 1 });
  assert.deepEqual(s2.rois.map((r) => r.id), [2]);
  assert.equal(s2.selected, 2);
  const s3 = roiReducer(s2, { type: "remove", id: 2 });
  assert.equal(s3.rois.length, 0);
  assert.equal(s3.selected, null);
  // ids are never reused
  assert.equal(s3.nextId, 3);
});

test("roiReducer select / clear", () => {
  const s = roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 2 } });
  assert.equal(roiReducer(s, { type: "select", id: null }).selected, null);
  assert.equal(roiReducer(s, { type: "select", id: 1 }).selected, 1);
  assert.equal(roiReducer(s, { type: "select", id: 99 }).selected, null);
  const c = roiReducer(s, { type: "clear" });
  assert.equal(c.rois.length, 0);
  assert.equal(c.nextId, 2);
});

test("normalizeRect orders corners, clamps to the image and rejects empty rects", () => {
  assert.deepEqual(normalizeRect(5, 4, 2, 1, W, H), { x0: 2, y0: 1, x1: 4, y1: 3 });
  assert.deepEqual(normalizeRect(-3, -3, 1, 1, W, H), { x0: 0, y0: 0, x1: 1, y1: 1 });
  assert.equal(normalizeRect(1, 1, 1, 1, W, H), null);
  assert.equal(normalizeRect(1, 1, 2, 1, W, H), null);
});

test("roiStats for a spot returns the pixel value", () => {
  const spot: Roi = { id: 1, kind: "spot", x: 2, y: 1 };
  assert.deepEqual(roiStats(FIELD, W, H, spot), { n: 1, nan: 0, min: 22, max: 22, mean: 22 });
});

test("roiStats for a spot on a NaN pixel reports n = 0", () => {
  const spot: Roi = { id: 1, kind: "spot", x: 2, y: 2 };
  assert.deepEqual(roiStats(FIELD, W, H, spot), { n: 0, nan: 1, min: null, max: null, mean: null });
});

test("roiStats for a rectangle ignores NaN and matches numpy semantics (half-open)", () => {
  const rect: Roi = { id: 2, kind: "rect", x0: 1, y0: 1, x1: 3, y1: 3 }; // 21 22 / 31 NaN
  const s = roiStats(FIELD, W, H, rect);
  assert.equal(s.n, 3);
  assert.equal(s.nan, 1);
  assert.equal(s.min, 21);
  assert.equal(s.max, 31);
  assert.ok(Math.abs((s.mean as number) - (21 + 22 + 31) / 3) < 1e-6);
});

test("roiStats for a spot outside the image reports n = 0 without throwing", () => {
  const spot: Roi = { id: 1, kind: "spot", x: 40, y: 1 };
  assert.equal(roiStats(FIELD, W, H, spot).n, 0);
});

test("roiLabel is short and stable", () => {
  assert.equal(roiLabel({ id: 3, kind: "spot", x: 0, y: 0 }), "S3");
  assert.equal(roiLabel({ id: 7, kind: "rect", x0: 0, y0: 0, x1: 1, y1: 1 }), "R7");
});

test("saveRois / loadRois round-trip and reject malformed storage", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  const s = roiReducer(roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 2 } }), { type: "add", roi: { kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2 } });
  saveRois(storage, s);
  assert.deepEqual(loadRois(storage), { ...s, selected: null });
  store.set("fri.rois.v1", JSON.stringify({ rois: [{ id: "x", kind: "spot" }, { id: 4, kind: "rect", x0: 0, y0: 0, x1: 3, y1: 3 }], nextId: 5 }));
  const l = loadRois(storage);
  assert.deepEqual(l.rois.map((r) => r.id), [4]);
  assert.equal(l.nextId, 5);
  store.set("fri.rois.v1", "not json");
  assert.deepEqual(loadRois(storage), EMPTY);
  assert.deepEqual(loadRois(null), EMPTY);
});
