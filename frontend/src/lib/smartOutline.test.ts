import assert from "node:assert/strict";
import { test } from "node:test";
import { labelContours, smartOutlines } from "./smartOutline.ts";

type Loop = [number, number][];
/** A loop as a sorted list of its corner points (start and direction do not matter). */
const corners = (l: Loop) => l.map(([x, y]) => `${x},${y}`).sort();

test("labelContours: one pixel is one square loop of its four corners", () => {
  const loops = labelContours(new Uint8Array([1]), 1, 1, 1);
  assert.equal(loops.length, 1);
  assert.deepEqual(corners(loops[0]), ["0,0", "0,1", "1,0", "1,1"]);
});

test("labelContours merges collinear steps: a 3x2 block is a 4-corner rectangle", () => {
  const loops = labelContours(new Uint8Array([1, 1, 1, 1, 1, 1]), 3, 2, 1);
  assert.equal(loops.length, 1);
  assert.deepEqual(corners(loops[0]), ["0,0", "0,2", "3,0", "3,2"]);
});

test("labelContours: two separate pixels are two loops", () => {
  const loops = labelContours(new Uint8Array([1, 0, 1]), 3, 1, 1);
  assert.equal(loops.length, 2);
});

test("labelContours: sample edge vs ring outer edge in a ring-wrapped crop", () => {
  const crop = new Uint8Array([2, 2, 2, 2, 1, 2, 2, 2, 2]);
  const sample = labelContours(crop, 3, 3, 1);
  assert.equal(sample.length, 1);
  assert.deepEqual(corners(sample[0]), ["1,1", "1,2", "2,1", "2,2"]);
  const ring = labelContours(crop, 3, 3, 2); // region {1..2}: the ring's outer boundary only
  assert.equal(ring.length, 1);
  assert.deepEqual(corners(ring[0]), ["0,0", "0,3", "3,0", "3,3"]);
});

test("labelContours: an L shape keeps its six corners", () => {
  // 1 1
  // 1 0
  const loops = labelContours(new Uint8Array([1, 1, 1, 0]), 2, 2, 1);
  assert.equal(loops.length, 1);
  assert.deepEqual(corners(loops[0]), ["0,0", "0,2", "1,1", "1,2", "2,0", "2,1"]);
});

// Literal from backend/tests/test_smart_roi.py KNOWN_VECTOR: crop [[0,1,1,0],[1,1,1,2],[2,2,2,2]]
const VECTOR = "AAEAAAABAgAAAAABAAAAAQMAAAACBQAAAA==";

test("smartOutlines places the crop at its bbox and splits sample / ring loops", () => {
  const o = smartOutlines({ id: 1, state: "locked", valid: true, bbox: [10, 20, 14, 23], labels: VECTOR });
  assert.ok(o);
  assert.equal(o.sample.length, 1);
  assert.deepEqual(corners(o.sample[0]), ["10,21", "10,22", "11,20", "11,21", "13,20", "13,22"]);
  assert.equal(o.rings.length, 1);
  assert.equal(o.rings[0].length, 1);
  assert.deepEqual(corners(o.rings[0][0]), ["10,21", "10,23", "11,20", "11,21", "13,20", "13,21", "14,21", "14,23"]);
});

test("smartOutlines: no labels (searching) or a malformed crop gives null", () => {
  assert.equal(smartOutlines({ id: 1, state: "searching", valid: false, bbox: null, labels: null }), null);
  assert.equal(smartOutlines({ id: 1, state: "locked", valid: true, bbox: [0, 0, 5, 5], labels: VECTOR }), null);
});

test("smartOutlineTokens: a stale stored outline is drawn muted (rings and sample), a current one in colour", async () => {
  const { smartOutlineTokens } = await import("./smartOutline.ts");
  assert.deepEqual(smartOutlineTokens(false), { rings: "--trace-3", sample: "--live" });
  assert.deepEqual(smartOutlineTokens(true), { rings: "--muted", sample: "--muted" });
});
