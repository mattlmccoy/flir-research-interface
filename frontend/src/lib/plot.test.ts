import { test } from "node:test";
import assert from "node:assert/strict";
import { niceTicks, TraceBuffer, valueRange, visibleWindow, xToPx, yToPx } from "./plot.ts";

test("niceTicks yields round steps that cover the range", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(21.3, 33.8, 5), [22, 24, 26, 28, 30, 32]);
  assert.deepEqual(niceTicks(0, 1, 4), [0, 0.2, 0.4, 0.6, 0.8, 1]);
});

test("niceTicks handles a degenerate range by padding around the value", () => {
  const t = niceTicks(25, 25, 4);
  assert.ok(t.length >= 2);
  assert.ok(t[0] <= 25 && t[t.length - 1] >= 25);
});

test("xToPx / yToPx map data to pixel space with y inverted", () => {
  assert.equal(xToPx(5, { t0: 0, t1: 10 }, 100), 50);
  assert.equal(yToPx(0, { min: 0, max: 100 }, 200), 200);
  assert.equal(yToPx(100, { min: 0, max: 100 }, 200), 0);
  assert.equal(yToPx(50, { min: 50, max: 50 }, 200), 100); // degenerate range centred
});

test("TraceBuffer keeps at most maxPoints, oldest dropped first, and is not mutated by readers", () => {
  const b = new TraceBuffer(3);
  b.push(0, 1); b.push(1, 2); b.push(2, 3); b.push(3, 4);
  assert.deepEqual(Array.from(b.t), [1, 2, 3]);
  assert.deepEqual(Array.from(b.v), [2, 3, 4]);
  assert.equal(b.length, 3);
});

test("TraceBuffer.push with a null value records a gap (NaN)", () => {
  const b = new TraceBuffer(4);
  b.push(0, 1); b.push(1, null); b.push(2, 3);
  assert.equal(b.length, 3);
  assert.ok(Number.isNaN(b.v[1]));
});

test("valueRange spans all finite values across traces with a small margin", () => {
  const r = valueRange([{ t: [0, 1], v: [20, 30] }, { t: [0, 1], v: [NaN, 25] }]);
  assert.ok(r !== null);
  assert.ok(r.min < 20 && r.min > 18);
  assert.ok(r.max > 30 && r.max < 32);
  assert.equal(valueRange([{ t: [0], v: [NaN] }]), null);
});

test("visibleWindow for live follows the newest sample; 'all' spans the data", () => {
  assert.deepEqual(visibleWindow(100, 60, 0), { t0: 40, t1: 100 });
  assert.deepEqual(visibleWindow(30, 60, 0), { t0: 0, t1: 60 });
  assert.deepEqual(visibleWindow(100, Infinity, 5), { t0: 5, t1: 100 });
  assert.deepEqual(visibleWindow(5, Infinity, 5), { t0: 5, t1: 6 });
});
