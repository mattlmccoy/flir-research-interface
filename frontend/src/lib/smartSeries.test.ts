import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { Smart } from "./roi.ts";
import { test } from "node:test";
import { isNotFound, parseSmartSeries, smartComputeAction, smartJobText, smartPlaybackRow, smartRowAt, type SmartSeries, type SmartSeriesState } from "./smartSeries.ts";

// Real API payload (see smartTraces.test.ts): rows 0, 36–45 searching; 1–5, 46–47 locked; 6–35 holding.
const FIX = JSON.parse(readFileSync(new URL("./fixtures/smart_series_20261020.json", import.meta.url), "utf8")) as Record<string, unknown> & { _capture: { missing_status: number; missing_body: { detail: string } } };
const series = (): SmartSeries => {
  const s = parseSmartSeries(FIX);
  assert.ok(s);
  return s;
};
const ready = (s: SmartSeries = series()): SmartSeriesState => ({ kind: "ready", series: s });

test("parseSmartSeries keeps the real payload's columns and rejects malformed ones", () => {
  const s = series();
  assert.equal(s.index.length, 48);
  assert.equal(s.rings.length, 3);
  assert.deepEqual([s.rings[1].inner_px, s.rings[1].outer_px], [5, 10]);
  assert.equal(s.stale, false);
  assert.equal(s.dims.area_px[1], 1034);
  assert.equal(parseSmartSeries(null), null);
  assert.equal(parseSmartSeries({ ...FIX, state: ["locked"] }), null, "column lengths disagree");
  assert.equal(parseSmartSeries({ ...FIX, state: (FIX.state as string[]).map(() => "lost") }), null, "unknown state");
});

test("isNotFound: only the API's 404 (how lib/api.ts j() words a failed response) means not computed", () => {
  // j() throws `${status} ${detail}`; the real 404 body was captured with the fixture
  assert.equal(FIX._capture.missing_status, 404);
  assert.equal(isNotFound(new Error(`404 ${FIX._capture.missing_body.detail}`)), true);
  assert.equal(isNotFound(new Error("500 Internal Server Error")), false);
  assert.equal(isNotFound(new TypeError("Failed to fetch")), false);
  assert.equal(isNotFound("404 nope"), false);
});

test("smartRowAt: the stored row at the playhead, or the nearest earlier stored point when downsampled", () => {
  const s = series();
  const r = smartRowAt(s, 5);
  assert.ok(r);
  assert.equal(r.frame, 5);
  assert.equal(r.exact, true);
  assert.equal(r.entry.state, "locked");
  assert.equal(r.entry.valid, true);
  assert.equal(r.entry.rings.length, 3);
  assert.equal(r.entry.dims?.area_px, 1172);
  const strided: SmartSeries = { ...s, index: s.index.map((i) => i * 2) };  // as if stride 2
  const near = smartRowAt(strided, 11);
  assert.ok(near);
  assert.equal(near.frame, 10);
  assert.equal(near.exact, false);
  assert.equal(smartRowAt(strided, -1), null);
});

test("smartRowAt: searching rows carry no numbers; holding rows are valid", () => {
  const s = series();
  const searching = smartRowAt(s, 40);
  assert.ok(searching);
  assert.equal(searching.entry.valid, false);
  assert.equal(searching.entry.dims, null);
  const holding = smartRowAt(s, 10);
  assert.ok(holding);
  assert.equal(holding.entry.state, "holding");
  assert.equal(holding.entry.valid, true);
});

test("smartPlaybackRow: readout at the playhead, never a number when unknown", () => {
  const locked = smartPlaybackRow(ready(), 5);
  assert.equal(locked.tone, "locked");
  assert.ok(locked.mean !== null && Math.abs(locked.mean - 111.02618369144791) < 1e-9);
  assert.match(locked.summary, /^locked · 111 °C · max 147 · area \d+ px$/);
  assert.deepEqual(locked.entry?.rings.map((g) => g.outer_px), [5, 10, 25], "the expanded table's rings");
  assert.deepEqual(locked.notes, []);
  const holding = smartPlaybackRow(ready(), 10);
  assert.equal(holding.tone, "holding");
  assert.equal(holding.marker, "holding");
  const searching = smartPlaybackRow(ready(), 40);
  assert.equal(searching.mean, null);
  assert.equal(searching.tone, "searching");
  for (const st of [{ kind: "loading" }, { kind: "missing" }, { kind: "error", message: "500 boom" }] as SmartSeriesState[]) {
    const v = smartPlaybackRow(st, 5);
    assert.equal(v.mean, null, st.kind);
    assert.equal(v.tone, "none", st.kind);
  }
  assert.match(smartPlaybackRow({ kind: "missing" }, 5).summary, /not computed/);
  assert.match(smartPlaybackRow({ kind: "error", message: "500 boom" }, 5).summary, /500 boom/);
});

test("smartPlaybackRow labels a downsampled reading and a stale series", () => {
  const s = series();
  const near = smartPlaybackRow(ready({ ...s, index: s.index.map((i) => i * 2) }), 11);
  assert.ok(near.notes.some((l) => /frame 11 .*nearest stored point/.test(l)), near.notes.join("\n"));
  assert.match(near.summary, / · ≈ frame 11$/, "the collapsed line keeps the ≈ marker");
  const stale = smartPlaybackRow(ready({ ...s, stale: true }), 5);
  assert.ok(stale.notes.some((l) => /stale/.test(l)));
  assert.match(stale.summary, / · stale$/, "the collapsed line keeps the stale marker");
});

test("smartComputeAction: compute when missing, recompute when stale or edited, nothing while running or fresh", () => {
  const s = series();
  assert.equal(smartComputeAction({ kind: "missing" }, null, false)?.label, "compute smart ROI");
  assert.equal(smartComputeAction(ready({ ...s, stale: true }), null, false)?.label, "recompute smart ROI");
  assert.equal(smartComputeAction(ready(), null, true)?.label, "recompute smart ROI", "ROI edited on screen since");
  assert.equal(smartComputeAction(ready(), null, false), null);
  assert.equal(smartComputeAction({ kind: "loading" }, null, false), null);
  const running = smartComputeAction({ kind: "missing" }, { state: "running", done: 10, total: 40, error: null }, false);
  assert.ok(running);
  assert.equal(running.disabled, true);
  // a failed fetch (not a 404) offers a retry, not a compute
  assert.equal(smartComputeAction({ kind: "error", message: "500" }, null, false)?.label, "retry loading");
});

test("smartJobText: progress, failure and idle", () => {
  assert.equal(smartJobText({ state: "running", done: 32, total: 128, error: null }), "computing… 32/128 frames (25 %)");
  assert.equal(smartJobText({ state: "running", done: 0, total: 0, error: null }), "computing…");
  assert.equal(smartJobText({ state: "error", done: 3, total: 9, error: "not temperature-linear" }), "compute failed: not temperature-linear");
  assert.equal(smartJobText({ state: "idle", done: 0, total: 0, error: null }), null);
  assert.equal(smartJobText(null), null);
});

test("smartEdited: only tracking settings count (a rename or recolour needs no recompute)", async () => {
  const { smartEdited } = await import("./smartSeries.ts");
  const stored = [
    { id: 2, kind: "spot", x: 1, y: 1 },
    { id: 3, kind: "smart", name: "graphite", search: [[0, 0], [10, 0], [10, 10]], rings_px: [5, 10, 25], rule: "relative", sensitivity: 0.5 },
  ];
  const r: Smart = { id: 3, kind: "smart", search: [[0, 0], [10, 0], [10, 10]], rings_px: [5, 10, 25], rule: "relative", sensitivity: 0.5 };
  assert.equal(smartEdited(r, stored), false);
  assert.equal(smartEdited({ ...r, name: "renamed", color: "#ff0000" }, stored), false);
  assert.equal(smartEdited({ ...r, sensitivity: 0.6 }, stored), true);
  assert.equal(smartEdited({ ...r, rings_px: [5, 10] }, stored), true);
  assert.equal(smartEdited({ ...r, search: [[1, 0], [10, 0], [10, 10]] }, stored), true);
  assert.equal(smartEdited({ ...r, ring_emissivity: 0.9 }, stored), true);
  assert.equal(smartEdited({ ...r, id: 9 }, stored), true, "not stored with the run yet");
  assert.equal(smartEdited(r, null), true);
});

test("smartEdited: a stored ROI that omits defaulted keys equals the on-screen one with defaults", async () => {
  const { smartEdited } = await import("./smartSeries.ts");
  // captured: GET /api/experiments/{name} `rois` of a run recorded with a freshly drawn smart ROI
  const stored = [{ id: 3, kind: "smart", name: "graphite", search: [[52, 86], [74, 86], [81, 85], [40, 43]] }];
  const onScreen: Smart = { id: 3, kind: "smart", name: "graphite", search: [[52, 86], [74, 86], [81, 85], [40, 43]], rings_px: [5, 10, 25], rule: "relative", sensitivity: 0.5 };
  assert.equal(smartEdited(onScreen, stored), false);
  assert.equal(smartEdited({ ...onScreen, sensitivity: 0.4 }, stored), true);
});

test("fix1: a stale series never looks current (stale marker, not the locked tone)", () => {
  const v = smartPlaybackRow(ready({ ...series(), stale: true }), 5);
  assert.notEqual(v.tone, "locked");
  assert.equal(v.tone, "invalid");
  assert.match(v.marker ?? "", /stale/);
  assert.ok(v.notes.some((l) => /stale/.test(l)));
});

test("fix1: an ROI edited on screen since the compute is treated as stale", () => {
  const v = smartPlaybackRow(ready(), 5, { edited: true });
  assert.notEqual(v.tone, "locked");
  assert.match(v.marker ?? "", /stale/);
  assert.ok(v.notes.some((l) => /edited/.test(l)));
  assert.match(v.summary, / · stale$/);
});

test("fix2: a downsampled (not exact) value is marked ≈ and not locked-toned", () => {
  const s = series();
  const v = smartPlaybackRow(ready({ ...s, index: s.index.map((i) => i * 2) }), 11);
  assert.ok(v.mean !== null);
  assert.match(v.marker ?? "", /≈/);
  assert.notEqual(v.tone, "locked");
});

test("fix2: the exact frame's overlay state gates the number (searching / invalid → no number)", () => {
  const s = series();
  const strided = ready({ ...s, index: s.index.map((i) => i * 2) });
  const searching = smartPlaybackRow(strided, 11, { overlay: { state: "searching", valid: false } });
  assert.equal(searching.mean, null);
  assert.equal(searching.tone, "searching");
  assert.equal(searching.marker, "searching");
  const invalid = smartPlaybackRow(strided, 11, { overlay: { state: "holding", valid: false } });
  assert.equal(invalid.mean, null);
  assert.equal(invalid.tone, "invalid");
  const ok = smartPlaybackRow(strided, 11, { overlay: { state: "locked", valid: true } });
  assert.ok(ok.mean !== null);
  assert.match(ok.marker ?? "", /≈/);
  // an exact locked row with a matching overlay stays plainly locked
  const exact = smartPlaybackRow(ready(), 5, { overlay: { state: "locked", valid: true } });
  assert.equal(exact.tone, "locked");
  assert.equal(exact.marker, null);
});

test("fix3: smartPollStep keeps polling a running job, reloads when done, stops on error/idle", async () => {
  const { smartPollStep, SMART_POLL_MS } = await import("./smartSeries.ts");
  const running = { state: "running" as const, done: 10, total: 40, error: null };
  const r = smartPollStep({ job: null, failures: 2 }, { ok: true, job: running });
  assert.deepEqual(r, { next: { job: running, failures: 0 }, action: "continue", delayMs: SMART_POLL_MS });
  assert.equal(smartPollStep({ job: running, failures: 0 }, { ok: true, job: { ...running, state: "done", done: 40 } }).action, "reload");
  assert.equal(smartPollStep({ job: running, failures: 0 }, { ok: true, job: { ...running, state: "error", error: "x" } }).action, "stop");
  assert.equal(smartPollStep({ job: running, failures: 0 }, { ok: true, job: { ...running, state: "idle" } }).action, "stop");
});

test("fix3: a failed status poll retries with backoff, then gives up as an error so the button returns", async () => {
  const { smartPollStep, smartComputeAction, SMART_POLL_MS } = await import("./smartSeries.ts");
  const running = { state: "running" as const, done: 10, total: 40, error: null };
  const fail = { ok: false as const, error: "TypeError: Failed to fetch" };
  const a = smartPollStep({ job: running, failures: 0 }, fail);
  assert.equal(a.action, "continue");
  assert.equal(a.next.failures, 1);
  assert.equal(a.next.job, running, "still shown as running while retrying");
  assert.ok(a.delayMs > SMART_POLL_MS);
  const b = smartPollStep(a.next, fail);
  assert.equal(b.action, "continue");
  assert.ok(b.delayMs > a.delayMs, "backoff grows");
  const c = smartPollStep(b.next, fail);
  assert.equal(c.action, "stop");
  assert.equal(c.next.job?.state, "error");
  assert.match(c.next.job?.error ?? "", /lost contact with the compute job/);
  assert.equal(smartComputeAction({ kind: "missing" }, c.next.job, false)?.disabled, false, "compute button comes back");
});

test("minor1: upsertStoredRoi replaces the same id or appends, leaving the other stored ROIs as stored", async () => {
  const { upsertStoredRoi } = await import("./smartSeries.ts");
  const stored = [{ id: 2, kind: "spot", x: 1, y: 1 }, { id: 3, kind: "smart", name: "graphite", search: [[0, 0], [9, 0], [9, 9]] }];
  const r: Smart = { id: 3, kind: "smart", name: "graphite", search: [[1, 0], [9, 0], [9, 9]], rings_px: [5, 10, 25], rule: "relative", sensitivity: 0.4 };
  assert.deepEqual(upsertStoredRoi(stored, r), [stored[0], r]);
  assert.deepEqual(upsertStoredRoi(stored, { ...r, id: 7 }), [...stored, { ...r, id: 7 }]);
  assert.deepEqual(upsertStoredRoi([], r), [r]);
  assert.equal(stored.length, 2, "input not mutated");
});

test("critical: upsertStoredRoi throws on a non-array stored list instead of PUTting [roi] over the run's ROIs", async () => {
  const { upsertStoredRoi } = await import("./smartSeries.ts");
  const r: Smart = { id: 3, kind: "smart", name: "graphite", search: [[1, 0], [9, 0], [9, 9]], rings_px: [5, 10, 25], rule: "relative", sensitivity: 0.4 };
  assert.throws(() => upsertStoredRoi(undefined, r), /stored ROI list/);
  assert.throws(() => upsertStoredRoi(null, r), /stored ROI list/);
  assert.throws(() => upsertStoredRoi({ rois: [] } as unknown as unknown[], r), /stored ROI list/);
});

test("parseSmartSeries keeps computed_utc (null when the operator sends none)", () => {
  assert.equal(series().computed_utc, FIX.computed_utc);
  assert.match(String(FIX.computed_utc), /^\d{4}-\d\d-\d\dT/);
  assert.equal(parseSmartSeries({ ...FIX, computed_utc: undefined })?.computed_utc, null);
});

test("seriesRecomputed: a reload that shows a different compute drops cached outlines; the first load does not", async () => {
  const { seriesRecomputed } = await import("./smartSeries.ts");
  assert.equal(seriesRecomputed(undefined, "2026-10-21T10:00:00+00:00"), false, "first load");
  assert.equal(seriesRecomputed("2026-10-21T10:00:00+00:00", "2026-10-21T10:00:00+00:00"), false, "same compute");
  assert.equal(seriesRecomputed("2026-10-21T10:00:00+00:00", "2026-10-21T11:00:00+00:00"), true, "recomputed elsewhere");
  assert.equal(seriesRecomputed(null, "2026-10-21T11:00:00+00:00"), true, "was missing, now computed");
});

test("saveSmartForCompute: waits for the run info refresh, so back-to-back computes never drop an upsert", async () => {
  const { saveSmartForCompute } = await import("./smartSeries.ts");
  const base = { id: 3, kind: "smart" as const, name: "graphite", search: [[1, 0], [9, 0], [9, 9]] as [number, number][], rings_px: [5, 10, 25], rule: "relative" as const, sensitivity: 0.5 };
  const spot = { id: 2, kind: "spot", x: 1, y: 1 };
  let server: unknown[] = [spot];
  const puts: unknown[][] = [];
  const events: string[] = [];
  let release: () => void = () => undefined;
  const io = {
    confirm: () => true,
    putRois: async (list: unknown[]) => { puts.push(list); server = list; },
    refresh: () => new Promise<{ rois: unknown[] }>((res) => { release = () => { events.push("refreshed"); res({ rois: server }); }; }),
  };
  const first = saveSmartForCompute(base, { rois: [spot] }, io).then((r) => { events.push("returned"); return r; });
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(events, [], "does not return before the refresh lands");
  release();
  const a = await first;
  assert.deepEqual(events, ["refreshed", "returned"]);
  assert.equal(a.ok, true);
  const second = saveSmartForCompute({ ...base, id: 7 }, a.info, io);
  await new Promise((r) => setTimeout(r, 0));
  release();
  await second;
  assert.deepEqual(puts[1], [spot, base, { ...base, id: 7 }], "the second upsert keeps the first one");
});

test("saveSmartForCompute: a failed refresh still carries the list it saved; unedited needs no save; cancel stops", async () => {
  const { saveSmartForCompute } = await import("./smartSeries.ts");
  const r = { id: 3, kind: "smart" as const, search: [[1, 0], [9, 0], [9, 9]] as [number, number][], rings_px: [5, 10, 25], rule: "relative" as const, sensitivity: 0.5 };
  const io = { confirm: () => true, putRois: async () => undefined, refresh: async (): Promise<{ rois: unknown[] }> => { throw new Error("offline"); } };
  const got = await saveSmartForCompute(r, { rois: [] }, io);
  assert.equal(got.ok, true);
  assert.deepEqual(got.info.rois, [r]);
  const same = await saveSmartForCompute(r, { rois: [r] }, { ...io, putRois: async () => { throw new Error("must not save"); } });
  assert.equal(same.ok, true);
  assert.equal((await saveSmartForCompute(r, { rois: [] }, { ...io, confirm: () => false })).ok, false);
});
