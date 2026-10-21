import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeLabels, labelEdges } from "./smartLabels.ts";

// Literal from backend/tests/test_smart_roi.py KNOWN_VECTOR: crop [[0,1,1,0],[1,1,1,2],[2,2,2,2]]
const VECTOR = "AAEAAAABAgAAAAABAAAAAQMAAAACBQAAAA==";

test("decodeLabels round-trips the Python encoder's vector", () => {
  const got = decodeLabels(VECTOR, 4, 3);
  assert.deepEqual(Array.from(got), [0, 1, 1, 0, 1, 1, 1, 2, 2, 2, 2, 2]);
});

test("decodeLabels rejects a run total that does not match w*h", () => {
  assert.throws(() => decodeLabels(VECTOR, 5, 3), /runs/);
});

test("labelEdges on a 3x3 sample in a 5x5 crop is the 8 border pixels", () => {
  const w = 5;
  const labels = new Uint8Array(25);
  for (let y = 1; y <= 3; y++) for (let x = 1; x <= 3; x++) labels[y * w + x] = 1;
  const edges = labelEdges(labels, w, 5);
  const idx = edges.map((e) => e.idx).sort((a, b) => a - b);
  assert.deepEqual(idx, [6, 7, 8, 11, 13, 16, 17, 18]);
  assert.ok(edges.every((e) => e.value === 1));
});

test("labelEdges never marks unlabelled pixels; the lower label is the inner side", () => {
  // 7x5 crop, 0 padding all round, sample (1) 3 wide next to ring (2) 2 wide, 3 rows tall
  const w = 7;
  const labels = new Uint8Array(35);
  for (let y = 1; y <= 3; y++) labels.set([1, 1, 1, 2, 2], y * w + 1);
  const idx = (e: { value: number; idx: number }[], v: number) =>
    e.filter((p) => p.value === v).map((p) => p.idx);
  const edges = labelEdges(labels, w, 5);
  assert.ok(edges.every((e) => labels[e.idx] === e.value && e.value !== 0));
  // sample: top/bottom rows (zero above/below) + left column + the column touching the ring
  assert.deepEqual(idx(edges, 1), [8, 9, 10, 15, 17, 22, 23, 24]);
  // ring: all but 18 (its neighbours are 1 on the left, 2 elsewhere: the lower label is not outer)
  assert.deepEqual(idx(edges, 2), [11, 12, 19, 25, 26]);
});

test("labelEdges treats outside the crop as unlabelled: a ring on the crop border is an edge", () => {
  // 5x5 of label 2 around a 3x3 of label 1 (bbox of labels>0 puts the outer ring on the border)
  const w = 5;
  const labels = new Uint8Array(25).fill(2);
  for (let y = 1; y <= 3; y++) for (let x = 1; x <= 3; x++) labels[y * w + x] = 1;
  const edges = labelEdges(labels, w, 5);
  const ring = edges.filter((e) => e.value === 2).map((e) => e.idx).sort((a, b) => a - b);
  const sample = edges.filter((e) => e.value === 1).map((e) => e.idx).sort((a, b) => a - b);
  // all 16 crop-border pixels (outside = 0 < 2 makes them edges); interior ring pixels none
  assert.deepEqual(ring, [0, 1, 2, 3, 4, 5, 9, 10, 14, 15, 19, 20, 21, 22, 23, 24]);
  // the 8 sample pixels next to the higher label 2; the centre (12) has no outer neighbour
  assert.deepEqual(sample, [6, 7, 8, 11, 13, 16, 17, 18]);
  assert.equal(edges.length, 24);
});
