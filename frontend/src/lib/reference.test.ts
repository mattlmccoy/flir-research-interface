import { test } from "node:test";
import assert from "node:assert/strict";
import { subtractReference, DIVERGING_RANGE } from "./reference.ts";

test("subtractReference returns field − reference, NaN where either is NaN, and a symmetric range", () => {
  const field = new Float32Array([25, 30, NaN, 40]);
  const ref = new Float32Array([20, 30, 30, NaN]);
  const out = subtractReference(field, ref);
  assert.deepEqual(Array.from(out.delta ?? []).map((v) => (Number.isNaN(v) ? "nan" : v)), [5, 0, "nan", "nan"]);
  assert.deepEqual(out.range, { min: -5, max: 5 }, "symmetric about zero so the diverging palette is centred");
  assert.equal(subtractReference(field, new Float32Array(3)).delta, null, "size mismatch → no subtraction");
  assert.deepEqual(DIVERGING_RANGE(0.2), { min: -1, max: 1 }, "never smaller than ±1 °C");
});
