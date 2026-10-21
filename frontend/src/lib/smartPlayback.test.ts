import assert from "node:assert/strict";
import { test } from "node:test";
import { overlayBlock, overlayOnError, overlayStore, pickOverlays, shownIndex, type OverlayCache } from "./smartPlayback.ts";
import type { SmartOverlay } from "./smartLabels.ts";

const ov = (id: number, state: SmartOverlay["state"]): SmartOverlay => ({ id, state, valid: state !== "searching", bbox: null, labels: null });

test("overlayBlock is the block start holding a frame index", () => {
  assert.equal(overlayBlock(0, 120), 0);
  assert.equal(overlayBlock(119, 120), 0);
  assert.equal(overlayBlock(120, 120), 120);
  assert.equal(overlayBlock(250, 120), 240);
});

test("pickOverlays takes each ROI's overlay for the index from its cached block", () => {
  const cache: OverlayCache = new Map<string, SmartOverlay[] | "missing">([
    ["1:120", [ov(1, "searching"), ov(1, "locked"), ov(1, "holding")]],
    ["2:120", "missing"],  // no stored series for ROI 2
  ]);
  assert.deepEqual(pickOverlays(cache, [1, 2], 121, 120), [ov(1, "locked")]);
  assert.deepEqual(pickOverlays(cache, [1], 125, 120), [], "past the end of the stored window");
  assert.deepEqual(pickOverlays(cache, [1], 5, 120), [], "block not loaded yet");
});

test("overlayOnError: only a 404 (not computed) is cached as missing; other failures are retried", () => {
  assert.equal(overlayOnError(new Error("404 no smart ROI series for ROI 3; compute it")), "missing");
  assert.equal(overlayOnError(new Error("500 Internal Server Error")), "retry");
  assert.equal(overlayOnError(new TypeError("Failed to fetch")), "retry");
});

// --- the overlay store: fetch, cache and abort overlay blocks (useSmartPlaybackOverlays wires it) ---

function fakeOverlayFetch() {
  const pending = new Map<string, { resolve: (v: SmartOverlay[]) => void; reject: (e: unknown) => void; signal: AbortSignal }>();
  const calls: string[] = [];
  const fetch = (id: number, start: number, signal: AbortSignal): Promise<SmartOverlay[]> => {
    calls.push(`${id}:${start}`);
    return new Promise((resolve, reject) => {
      pending.set(`${id}:${start}`, { resolve, reject, signal });
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    });
  };
  return { fetch, calls, pending };
}
const block = (id: number, n: number, state: SmartOverlay["state"] = "locked") => Array.from({ length: n }, () => ov(id, state));

test("ensure resolves once the block is cached, so the frame and its outline appear together", async () => {
  const f = fakeOverlayFetch();
  let changes = 0;
  const S = overlayStore(f.fetch, 4, { onChange: () => { changes++; }, onRetry: () => undefined });
  let done = false;
  const p = S.ensure([1], 5).then(() => { done = true; });
  await Promise.resolve();
  assert.equal(done, false, "not ready while the overlay block is still loading");
  assert.deepEqual(S.pick([1], 5), []);
  f.pending.get("1:4")?.resolve(block(1, 4));
  await p;
  assert.equal(S.pick([1], 5).length, 1);
  assert.ok(changes > 0);
  await S.ensure([1], 6);
  assert.deepEqual(f.calls, ["1:4"], "a cached block is not fetched again");
});

test("ensure: a 404 is cached as missing (no outline), a transient failure resolves and asks for a retry", async () => {
  const f = fakeOverlayFetch();
  let retries = 0;
  const S = overlayStore(f.fetch, 4, { onChange: () => undefined, onRetry: () => { retries++; } }, { schedule: (fn) => fn() });
  const p = S.ensure([1, 2], 0);
  f.pending.get("1:0")?.reject(new Error("404 no smart ROI series for ROI 1; compute it"));
  f.pending.get("2:0")?.reject(new Error("500 Internal Server Error"));
  await p;  // the frame is not held back forever by a flaky overlay fetch
  assert.equal(S.cache.get("1:0"), "missing");
  assert.equal(S.cache.has("2:0"), false, "a transient failure is never cached");
  assert.equal(retries, 1);
});

test("an aborted overlay fetch is neither cached as missing nor retried, and ensure rejects as an abort", async () => {
  const f = fakeOverlayFetch();
  let retries = 0;
  const S = overlayStore(f.fetch, 4, { onChange: () => undefined, onRetry: () => { retries++; } });
  const p = S.ensure([1], 0).then(() => "resolved", (e: unknown) => e);
  S.retain([8]);  // the playhead moved on to block 8
  const got = await p;
  assert.equal((got as { name?: string }).name, "AbortError");
  assert.equal(S.cache.has("1:0"), false);
  assert.equal(retries, 0);
  assert.equal(f.pending.get("1:0")?.signal.aborted, true);
});

test("retain keeps the overlay blocks of the wanted frames running", () => {
  const f = fakeOverlayFetch();
  const S = overlayStore(f.fetch, 4, { onChange: () => undefined, onRetry: () => undefined });
  void S.ensure([1], 0).catch(() => undefined);
  void S.ensure([1], 4).catch(() => undefined);
  S.retain([3, 4]);  // frame 3 (block 0) shown, frame 4 (block 4) prefetched
  assert.equal(f.pending.get("1:0")?.signal.aborted, false);
  assert.equal(f.pending.get("1:4")?.signal.aborted, false);
  S.abortAll();
  assert.equal(f.pending.get("1:0")?.signal.aborted, true);
});

test("shownIndex is the index of the frame on screen, never the playhead", () => {
  assert.equal(shownIndex({ header: { index: 42 } }), 42);
  assert.equal(shownIndex(null), null, "nothing on screen: no outline");
  assert.equal(shownIndex({ header: {} }), null);
});

// --- review round: a persistent 5xx backs off instead of refetching on every frame ---
test("a transient failure backs off: no refetch and no wait inside the window, one coalesced retry", async () => {
  const f = fakeOverlayFetch();
  let now = 1000, retries = 0;
  const timers: (() => void)[] = [];
  const S = overlayStore(f.fetch, 4, { onChange: () => undefined, onRetry: () => { retries++; } },
    { now: () => now, backoffMs: 3000, schedule: (fn) => { timers.push(fn); } });
  const p = S.ensure([1, 2], 0);
  f.pending.get("1:0")?.reject(new Error("500 Internal Server Error"));
  f.pending.get("2:0")?.reject(new Error("502 Bad Gateway"));
  await p;
  assert.equal(timers.length, 1, "two failures, one retry timer");
  now += 1000;
  await S.ensure([1, 2], 1);  // resolves at once: the frame shows without its outline
  assert.deepEqual(f.calls, ["1:0", "2:0"], "no refetch inside the back-off window");
  timers[0]();
  assert.equal(retries, 1);
  now += 2500;  // past the window
  void S.ensure([1], 2).catch(() => undefined);
  assert.deepEqual(f.calls, ["1:0", "2:0", "1:0"], "refetched once the window is over");
});
