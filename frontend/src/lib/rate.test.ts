import { test } from "node:test";
import assert from "node:assert/strict";
import { TraceBuffer } from "./plot.ts";
import { DEFAULT_RATE_ALARM, evalRateAlarm, loadRateAlarm, saveRateAlarm, slopeOver, type RateAlarmConfig } from "./rate.ts";

function buf(pts: [number, number][], cap = 1000): TraceBuffer {
  const b = new TraceBuffer(cap);
  for (const [t, v] of pts) b.push(t, v);
  return b;
}

test("slopeOver: exact on a ramp, uses only the window, robust to alternating noise", () => {
  const ramp = Array.from({ length: 100 }, (_, i) => [i / 15, 25 + 3 * (i / 15)] as [number, number]);
  assert.ok(Math.abs((slopeOver(buf(ramp), 2) as number) - 3) < 1e-9);
  // flat for a while, then 10 °C/s over the last 2 s: the window only sees the ramp
  const kink = Array.from({ length: 150 }, (_, i) => { const t = i / 15; return [t, t < 8 ? 25 : 25 + 10 * (t - 8)] as [number, number]; });
  assert.ok(Math.abs((slopeOver(buf(kink), 1.5) as number) - 10) < 1e-6);
  const noisy = Array.from({ length: 60 }, (_, i) => [i / 15, 25 + (i % 2 ? 0.1 : -0.1)] as [number, number]);
  assert.ok(Math.abs(slopeOver(buf(noisy), 2) as number) < 0.2, "±0.1 °C noise is not a heating rate");
});

test("slopeOver: null until the window is half full, skips NaN, survives ring wrap", () => {
  assert.equal(slopeOver(buf([[0, 1], [0.1, 2]]), 2), null);
  assert.equal(slopeOver(buf([[0, 1], [0.1, 2], [0.2, 3], [0.3, 4]]), 2), null, "0.3 s of data for a 2 s window");
  const withNan = buf([[0, 0], [0.5, NaN], [1, 2], [1.5, 3], [2, 4]]);
  assert.ok(Math.abs((slopeOver(withNan, 2) as number) - 2) < 0.2);
  const ring = buf(Array.from({ length: 50 }, (_, i) => [i, 2 * i] as [number, number]), 10);
  assert.ok(Math.abs((slopeOver(ring, 5) as number) - 2) < 1e-9);
});

const cfg = (p: Partial<RateAlarmConfig> = {}): RateAlarmConfig => ({ ...DEFAULT_RATE_ALARM, on: true, threshold: 10, ...p });
const idle = { tripped: false, roi: null, rate: null };

test("alarm trips at the threshold, holds with hysteresis, re-arms below 80 %", () => {
  let s = evalRateAlarm(new Map([[1, 9.9]]), cfg(), idle);
  assert.equal(s.tripped, false);
  s = evalRateAlarm(new Map([[1, 10]]), cfg(), s);
  assert.deepEqual(s, { tripped: true, roi: 1, rate: 10 });
  s = evalRateAlarm(new Map([[1, 8.5]]), cfg(), s);
  assert.equal(s.tripped, true, "8.5 is still above the 8.0 re-arm level");
  s = evalRateAlarm(new Map([[1, 7.9]]), cfg(), s);
  assert.equal(s.tripped, false);
});

test("alarm watches one ROI or the fastest of any; off or no data never trips", () => {
  const rates = new Map<number, number | null>([[1, 2], [2, 15], [3, null]]);
  assert.deepEqual(evalRateAlarm(rates, cfg({ roi: "any" }), idle), { tripped: true, roi: 2, rate: 15 });
  assert.equal(evalRateAlarm(rates, cfg({ roi: 1 }), idle).tripped, false);
  assert.equal(evalRateAlarm(rates, cfg({ on: false }), idle).tripped, false);
  assert.equal(evalRateAlarm(new Map([[3, null]]), cfg({ roi: 3 }), idle).tripped, false);
});

test("alarm config round-trips and falls back to defaults on garbage", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  assert.deepEqual(loadRateAlarm(storage), DEFAULT_RATE_ALARM);
  saveRateAlarm(storage, cfg({ roi: 4, stat: "mean", windowS: 5 }));
  assert.deepEqual(loadRateAlarm(storage), cfg({ roi: 4, stat: "mean", windowS: 5 }));
  store.set("fri.rateAlarm.v1", JSON.stringify({ on: "yes", threshold: -3, roi: "x" }));
  assert.deepEqual(loadRateAlarm(storage), DEFAULT_RATE_ALARM);
});
