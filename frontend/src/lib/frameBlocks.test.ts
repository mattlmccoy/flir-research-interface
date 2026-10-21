import assert from "node:assert/strict";
import { test } from "node:test";
import { blockLoader, ensureLatest, isAbort, loadFailure, wantedBlocks } from "./frameBlocks.ts";

/** A fetch that never settles on its own: it resolves on `finish(start)` or rejects on abort. */
function fakeFetch() {
  const pending = new Map<number, { resolve: (v: string) => void; signal: AbortSignal }>();
  const calls: number[] = [];
  const fetch = (start: number, signal: AbortSignal): Promise<string> => {
    calls.push(start);
    return new Promise<string>((resolve, reject) => {
      pending.set(start, { resolve, signal });
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    });
  };
  const finish = (start: number) => { pending.get(start)?.resolve(`block ${start}`); };
  return { fetch, finish, calls, pending };
}

test("wantedBlocks: the playhead's block, plus the next one in its last `lead` frames", () => {
  assert.deepEqual(wantedBlocks(0, 1000, 60, 20), [0]);
  assert.deepEqual(wantedBlocks(39, 1000, 60, 20), [0]);
  assert.deepEqual(wantedBlocks(40, 1000, 60, 20), [0, 60], "prefetch so 1x playback never waits");
  assert.deepEqual(wantedBlocks(130, 1000, 60, 20), [120]);
  assert.deepEqual(wantedBlocks(170, 180, 60, 20), [120], "no block past the end");
  assert.deepEqual(wantedBlocks(5, 0, 60, 20), [], "no frames, nothing wanted");
});

test("ensure fetches a block once and hands the data on", async () => {
  const f = fakeFetch();
  const got: string[] = [];
  const L = blockLoader(f.fetch, (_s, d: string) => got.push(d));
  const a = L.ensure(60), b = L.ensure(60);
  assert.equal(a, b, "a second ensure joins the running fetch");
  f.finish(60);
  await a;
  assert.deepEqual(got, ["block 60"]);
  assert.deepEqual(f.calls, [60]);
  assert.deepEqual(L.inflight(), []);
});

test("retain aborts the fetches nothing needs any more, and only those", async () => {
  const f = fakeFetch();
  const L = blockLoader(f.fetch, () => undefined);
  const scrubbed = [0, 60, 120, 180].map((s) => L.ensure(s).catch((e: unknown) => e));
  assert.deepEqual(L.retain([180, 240]), [0, 60, 120]);
  assert.deepEqual(L.inflight(), [180]);
  assert.equal(f.pending.get(0)?.signal.aborted, true);
  assert.equal(f.pending.get(180)?.signal.aborted, false);
  const errs = await Promise.all(scrubbed.slice(0, 3));
  assert.ok(errs.every(isAbort), "the dropped fetches reject as aborts");
});

test("an aborted block is not remembered: asking again fetches it fresh", async () => {
  const f = fakeFetch();
  const got: string[] = [];
  const L = blockLoader(f.fetch, (_s, d: string) => got.push(d));
  const first = L.ensure(60).catch((e: unknown) => e);
  L.retain([]);
  const again = L.ensure(60);  // the playhead came back before the abort settled
  assert.notEqual(again, first);
  assert.deepEqual(f.calls, [60, 60]);
  f.finish(60);
  await again;
  assert.ok(isAbort(await first));
  assert.deepEqual(got, ["block 60"], "only the fresh fetch delivers data");
  assert.deepEqual(L.inflight(), [], "the settled abort does not drop the fresh entry's bookkeeping late");
});

test("abortAll drops every running fetch", () => {
  const f = fakeFetch();
  const L = blockLoader(f.fetch, () => undefined);
  void L.ensure(0).catch(() => undefined);
  void L.ensure(60).catch(() => undefined);
  L.abortAll();
  assert.deepEqual(L.inflight(), []);
  assert.ok([...f.pending.values()].every((p) => p.signal.aborted));
});

test("isAbort tells an abort apart from a real failure", () => {
  assert.equal(isAbort(new DOMException("aborted", "AbortError")), true);
  assert.equal(isAbort(new Error("500 boom")), false);
  assert.equal(isAbort(new TypeError("Failed to fetch")), false);
  assert.equal(isAbort(null), false);
});

// --- review round: a store swap mid-ensure, and which load failures may show ---

const abortErr = () => new DOMException("aborted", "AbortError");

test("ensureLatest: an abort caused by a store swap is retried against the current store", async () => {
  const calls: string[] = [];
  const oldStore = (i: number) => { calls.push(`old ${i}`); return Promise.reject(abortErr()); };  // abortAll() on swap
  const newStore = (i: number) => { calls.push(`new ${i}`); return Promise.resolve(); };
  let current: (i: number) => Promise<void> = oldStore;
  const p = ensureLatest(() => current, 7);
  current = newStore;  // smart.version bumped while the old ensure was in flight
  await p;  // resolves: the frame is not left "loading" forever
  assert.deepEqual(calls, ["old 7", "new 7"]);
});

test("ensureLatest: an abort from the same store (the playhead moved on) is passed on", async () => {
  const same = () => Promise.reject(abortErr());
  await assert.rejects(ensureLatest(() => same, 3), (e: unknown) => isAbort(e));
});

test("ensureLatest gives up after a bounded number of swaps", async () => {
  let k = 0;
  const get = () => { k++; return () => Promise.reject(abortErr()); };  // a new store every time
  await assert.rejects(ensureLatest(get, 1, 3), (e: unknown) => isAbort(e));
  assert.ok(k <= 4);
});

test("loadFailure: aborts and loads for a frame no longer wanted are silent, never 'AbortError' on screen", () => {
  assert.equal(loadFailure(abortErr(), true), null);
  assert.equal(loadFailure(new Error("500 boom"), false), null, "scrubbed away: not this frame's error");
  assert.equal(loadFailure(new Error("500 boom"), true), "Error: 500 boom");
});
