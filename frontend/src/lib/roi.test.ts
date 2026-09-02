import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeRect,
  roiLabel,
  roiReducer,
  roiStats,
  loadRois,
  saveRois,
  visibleRois,
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

// ---- new geometries (circle, line, polyline) --------------------------------------------------

test("roiStats for a circle counts the pixels whose centres fall inside the disc", () => {
  // 8x8 field of ones; circle centre (3,3) radius 2 → the classic 13-pixel disc
  const f = new Float32Array(64).fill(1);
  const s = roiStats(f, 8, 8, { id: 1, kind: "circle", cx: 3, cy: 3, r: 2 });
  assert.equal(s.n, 13);
  assert.equal(s.mean, 1);
});

test("roiStats for a line samples every pixel along the segment (both endpoints inclusive)", () => {
  // 5x5 field where value = x + 10*y
  const f = new Float32Array(25);
  for (let y = 0; y < 5; y++) for (let x = 0; x < 5; x++) f[y * 5 + x] = x + 10 * y;
  const s = roiStats(f, 5, 5, { id: 2, kind: "line", x0: 0, y0: 0, x1: 4, y1: 0 });
  assert.equal(s.n, 5);
  assert.equal(s.min, 0);
  assert.equal(s.max, 4);
  assert.equal(s.mean, 2);
  const d = roiStats(f, 5, 5, { id: 3, kind: "line", x0: 0, y0: 0, x1: 4, y1: 4 }); // diagonal: 0,11,22,33,44
  assert.equal(d.n, 5);
  assert.equal(d.max, 44);
});

test("roiStats for a polygon covers the enclosed pixels (even-odd fill, boundary inclusive)", () => {
  const f = new Float32Array(25).fill(2);
  const tri = roiStats(f, 5, 5, { id: 4, kind: "polygon", points: [[0, 0], [4, 0], [4, 4]] });
  assert.equal(tri.n, 15); // right triangle incl. its edges: 5+4+3+2+1
  const sq = roiStats(f, 5, 5, { id: 5, kind: "polygon", points: [[1, 1], [3, 1], [3, 3], [1, 3]] });
  assert.equal(sq.n, 9);
});

test("roiStats clips circles and lines to the image and reports out-of-image parts as absent", () => {
  const f = new Float32Array(16).fill(5);
  const c = roiStats(f, 4, 4, { id: 5, kind: "circle", cx: 0, cy: 0, r: 1 }); // quarter disc: (0,0),(1,0),(0,1)
  assert.equal(c.n, 3);
  const l = roiStats(f, 4, 4, { id: 6, kind: "line", x0: 2, y0: 2, x1: 9, y1: 2 });
  assert.equal(l.n, 2); // x=2,3 inside
});

test("roiLabel prefixes: circle C, line L, polyline P", () => {
  assert.equal(roiLabel({ id: 1, kind: "circle", cx: 0, cy: 0, r: 1 }), "C1");
  assert.equal(roiLabel({ id: 2, kind: "line", x0: 0, y0: 0, x1: 1, y1: 1 }), "L2");
  assert.equal(roiLabel({ id: 3, kind: "polygon", points: [[0, 0], [1, 1], [0, 1]] }), "P3");
  assert.equal(roiLabel({ id: 4, kind: "spot", x: 0, y: 0, name: "melt pool" }), "melt pool");
});

test("loadRois accepts the new kinds and rejects malformed ones", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  store.set("fri.rois.v1", JSON.stringify({ rois: [
    { id: 1, kind: "circle", cx: 5, cy: 5, r: 3 },
    { id: 2, kind: "circle", cx: 5, cy: 5, r: 0 },
    { id: 3, kind: "line", x0: 0, y0: 0, x1: 3, y1: 3 },
    { id: 4, kind: "polygon", points: [[0, 0], [1, 1], [2, 0]], name: "n", color: "#ff0000" },
    { id: 5, kind: "polygon", points: [[0, 0], [1, 1]] },
    { id: 6, kind: "spot", x: 1, y: 1, color: "red" },
  ], nextId: 7 }));
  const got = loadRois(storage).rois;
  assert.deepEqual(got.map((r) => r.id), [1, 3, 4, 6]);
  assert.equal(got[2].name, "n"); assert.equal(got[2].color, "#ff0000");
  assert.equal(got[3].color, undefined); // only #rrggbb colours survive
});


test("roiReducer move shifts every coordinate of the shape (and never below zero)", () => {
  const base = roiReducer(roiReducer(roiReducer(roiReducer(EMPTY,
    { type: "add", roi: { kind: "rect", x0: 1, y0: 1, x1: 3, y1: 3 } }),
    { type: "add", roi: { kind: "circle", cx: 5, cy: 5, r: 2 } }),
    { type: "add", roi: { kind: "line", x0: 0, y0: 0, x1: 2, y1: 2 } }),
    { type: "add", roi: { kind: "polygon", points: [[0, 0], [2, 0], [1, 2]] } });
  const s = roiReducer(roiReducer(roiReducer(roiReducer(base,
    { type: "move", id: 1, dx: 2, dy: -5 }), { type: "move", id: 2, dx: 1, dy: 1 }), { type: "move", id: 3, dx: 1, dy: 0 }), { type: "move", id: 4, dx: 3, dy: 3 });
  assert.deepEqual(s.rois[0], { id: 1, kind: "rect", x0: 3, y0: 0, x1: 5, y1: 2 }); // clamped: keeps its size
  assert.deepEqual(s.rois[1], { id: 2, kind: "circle", cx: 6, cy: 6, r: 2 });
  assert.deepEqual(s.rois[2], { id: 3, kind: "line", x0: 1, y0: 0, x1: 3, y1: 2 });
  assert.deepEqual(s.rois[3], { id: 4, kind: "polygon", points: [[3, 3], [5, 3], [4, 5]] });
});

test("roiReducer rename and recolor set or clear the optional fields", () => {
  const s0 = roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 1 } });
  const s1 = roiReducer(s0, { type: "rename", id: 1, name: "  core  " });
  assert.equal(s1.rois[0].name, "core");
  assert.equal(roiReducer(s1, { type: "rename", id: 1, name: "" }).rois[0].name, undefined);
  const s2 = roiReducer(s1, { type: "recolor", id: 1, color: "#00ff00" });
  assert.equal(s2.rois[0].color, "#00ff00");
  assert.equal(roiReducer(s2, { type: "recolor", id: 1, color: null }).rois[0].color, undefined);
});

test("roiReducer replace swaps in a recording's ROI set, keeps ids unique afterwards", () => {
  const s0 = roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 1 } });
  const s = roiReducer(s0, { type: "replace", rois: [
    { id: 7, kind: "spot", x: 2, y: 2, name: "a" },
    { id: 9, kind: "rect", x0: 0, y0: 0, x1: 4, y1: 4 },
  ] });
  assert.deepEqual(s.rois.map((r) => r.id), [7, 9]);
  assert.equal(s.selected, null);
  assert.equal(roiReducer(s, { type: "add", roi: { kind: "spot", x: 0, y: 0 } }).rois[2].id, 10);
});

test("hide/show: toggleHidden flips one ROI, setHiddenAll sets every ROI, visibleRois filters", () => {
  let s = roiReducer(EMPTY, { type: "add", roi: { kind: "spot", x: 1, y: 1 } });
  s = roiReducer(s, { type: "add", roi: { kind: "rect", x0: 0, y0: 0, x1: 2, y1: 2 } });
  s = roiReducer(s, { type: "toggleHidden", id: 1 });
  assert.deepEqual(s.rois.map((r) => !!r.hidden), [true, false]);
  assert.deepEqual(visibleRois(s.rois).map((r) => r.id), [2]);
  s = roiReducer(s, { type: "toggleHidden", id: 1 });
  assert.deepEqual(s.rois.map((r) => !!r.hidden), [false, false]);
  s = roiReducer(s, { type: "setHiddenAll", hidden: true });
  assert.deepEqual(visibleRois(s.rois), []);
  assert.equal(s.selected, null, "hiding everything drops the selection");
  s = roiReducer(s, { type: "setHiddenAll", hidden: false });
  assert.equal(visibleRois(s.rois).length, 2);
  // hidden survives a save/load round trip
  s = roiReducer(s, { type: "toggleHidden", id: 2 });
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveRois(storage, s);
  assert.deepEqual(loadRois(storage).rois.map((r) => !!r.hidden), [false, true]);
});
