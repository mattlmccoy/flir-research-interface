import { test } from "node:test";
import assert from "node:assert/strict";
import type { VisibleAdjust } from "./visibleAdjust.ts";
import { canReset, createAdjustWriter, saveReducer, saveStateFor, type SaveAction, type SaveTrack } from "./visibleAdjustSave.ts";

const A: VisibleAdjust = { exposure_ev: 1, brightness: 0, contrast: 1 };
const IDLE: SaveTrack = { n: 0, save: { state: "idle" } };

/** A writer with a manual timer and recorded calls; `fail` makes the next write or clear reject. */
function harness() {
  const calls: string[] = [];
  let state = IDLE;
  const timers = new Map<number, () => void>();
  let tid = 0;
  const fail = { write: false, clear: false };
  const w = createAdjustWriter({
    write: async (name, a) => { calls.push(`put ${name} ${a.exposure_ev}`); if (fail.write) throw new Error("disk full"); },
    clear: async (name) => { calls.push(`delete ${name}`); if (fail.clear) throw new Error("offline"); },
    onAction: (a: SaveAction) => { state = saveReducer(state, a); },
    setTimer: (fn) => { const id = ++tid; timers.set(id, fn); return id; },
    clearTimer: (id) => { timers.delete(id as number); },
    debounceMs: 500,
  });
  return { w, calls, fail, timers, get state() { return state; } };
}

test("a slider move saves after the debounce; flush sends it at once and waits for it", async () => {
  const h = harness();
  h.w.set("runA", A);
  assert.deepEqual(h.calls, []); // debounced
  assert.deepEqual(h.state.save, { state: "saving", name: "runA", op: "save" });
  await h.w.flush();
  assert.deepEqual(h.calls, ["put runA 1"]);
  assert.equal(h.timers.size, 0); // the debounce timer is cancelled, so nothing is sent twice
  assert.deepEqual(h.state.save, { state: "idle" });
  await h.w.flush(); // nothing pending: resolves, sends nothing
  assert.deepEqual(h.calls, ["put runA 1"]);
});

test("flush resolves (never rejects) after a failed save, and the error names its run", async () => {
  const h = harness();
  h.fail.write = true;
  h.w.set("runA", A);
  await h.w.flush();
  assert.deepEqual(h.state.save, { state: "error", name: "runA", op: "save", error: "Error: disk full" });
  // run B does not show run A's failure
  assert.deepEqual(saveStateFor(h.state.save, "runB"), { state: "idle" });
  assert.deepEqual(saveStateFor(h.state.save, "runA"), h.state.save);
});

test("a failed reset keeps reset enabled so it can be retried; a good one disables it", async () => {
  const h = harness();
  h.fail.clear = true;
  h.w.reset("runA");
  await h.w.flush();
  assert.deepEqual(h.state.save, { state: "error", name: "runA", op: "reset", error: "Error: offline" });
  assert.equal(canReset("neutral", saveStateFor(h.state.save, "runA")), true);
  assert.equal(canReset("neutral", saveStateFor(h.state.save, "runB")), false);
  h.fail.clear = false;
  h.w.reset("runA");
  await h.w.flush();
  assert.deepEqual(h.calls, ["delete runA", "delete runA"]);
  assert.equal(canReset("recorded", h.state.save), false);
  assert.equal(canReset("sidecar", h.state.save), true);
});

test("reset drops a pending slider save; writes go out in order", async () => {
  const h = harness();
  h.w.set("runA", A);
  h.w.reset("runA");
  await h.w.flush();
  assert.deepEqual(h.calls, ["delete runA"]);
  h.w.set("runA", A);
  void h.w.flush();
  h.w.set("runA", { ...A, exposure_ev: 2 });
  await h.w.flush();
  assert.deepEqual(h.calls, ["delete runA", "put runA 1", "put runA 2"]);
});

test("saveReducer ignores the outcome of an older write", () => {
  let s = saveReducer(IDLE, { type: "start", n: 1, name: "runA", op: "save" });
  s = saveReducer(s, { type: "start", n: 2, name: "runA", op: "save" });
  assert.deepEqual(saveReducer(s, { type: "fail", n: 1, error: "old" }), s);
  assert.deepEqual(saveReducer(s, { type: "done", n: 1 }), s);
  assert.deepEqual(saveReducer(s, { type: "done", n: 2 }).save, { state: "idle" });
  assert.deepEqual(saveReducer(s, { type: "clear" }).save, { state: "idle" });
});
