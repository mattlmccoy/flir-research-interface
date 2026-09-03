import { test } from "node:test";
import assert from "node:assert/strict";
import { simplifyPath } from "./geometry.ts";

test("simplifyPath drops collinear and near-collinear points (Douglas–Peucker) but keeps corners", () => {
  const pts: [number, number][] = [[0, 0], [1, 0], [2, 0], [3, 0], [3, 1], [3, 2], [3, 3]];
  assert.deepEqual(simplifyPath(pts, 0.5), [[0, 0], [3, 0], [3, 3]]);
  const wiggle: [number, number][] = [[0, 0], [5, 0.3], [10, 0], [15, -0.4], [20, 0]];
  assert.deepEqual(simplifyPath(wiggle, 1), [[0, 0], [20, 0]]);
  assert.deepEqual(simplifyPath([[1, 1]], 1), [[1, 1]]);
});
