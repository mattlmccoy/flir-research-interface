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
  assert.throws(() => decodeLabels(VECTOR, 5, 3));
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

test("labelEdges marks the inner side of each boundary, never the unlabelled side", () => {
  // 1 1 2 2 0 : sample|ring boundary -> sample px (1) inner; ring|none -> ring px (2) inner
  const edges = labelEdges(new Uint8Array([1, 1, 2, 2, 0]), 5, 1);
  assert.deepEqual(edges, [
    { value: 1, idx: 1 },
    { value: 2, idx: 3 },
  ]);
});
