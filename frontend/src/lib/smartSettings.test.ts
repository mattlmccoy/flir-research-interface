import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRingOffsets } from "./smartSettings.ts";

test("parseRingOffsets reads a comma list of px offsets", () => {
  assert.deepEqual(parseRingOffsets("5, 10, 25"), { ok: true, rings: [5, 10, 25] });
  assert.deepEqual(parseRingOffsets(" 3,8 "), { ok: true, rings: [3, 8] });
  assert.deepEqual(parseRingOffsets("4"), { ok: true, rings: [4] });
});

test("parseRingOffsets rejects what the operator rejects", () => {
  for (const bad of ["", " , ", "5, x", "0, 5", "-5", "5, 5", "10, 5", "2.5, 5", "5,,10"]) {
    const got = parseRingOffsets(bad);
    assert.equal(got.ok, false, `should reject ${JSON.stringify(bad)}`);
  }
});

test("parseRingOffsets explains the problem", () => {
  const got = parseRingOffsets("10, 5");
  assert.equal(got.ok, false);
  if (!got.ok) assert.match(got.error, /increasing/);
});

test("parseRingOffsets caps the outermost ring at MAX_RING_PX (100 px), like the operator", async () => {
  const { MAX_RING_PX } = await import("./roi.ts");
  assert.equal(MAX_RING_PX, 100);
  assert.deepEqual(parseRingOffsets("5, 10, 100"), { ok: true, rings: [5, 10, 100] });
  const got = parseRingOffsets("5, 10, 101");
  assert.equal(got.ok, false);
  if (!got.ok) assert.match(got.error, /100 px/);
});
