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
  assert.equal(s.dims.area_px[1], 903);
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
  assert.equal(r.entry.dims?.area_px, 1077);
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
  assert.ok(locked.mean !== null && Math.abs(locked.mean - 113.36285751753641) < 1e-9);
  assert.match(locked.lines[0], /^locked · mean 113 °C · max 147/);
  assert.ok(locked.lines.some((l) => l.startsWith("ring 10–25 px")));
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
  assert.match(smartPlaybackRow({ kind: "missing" }, 5).lines[0], /not computed/);
  assert.match(smartPlaybackRow({ kind: "error", message: "500 boom" }, 5).lines[0], /500 boom/);
});

test("smartPlaybackRow labels a downsampled reading and a stale series", () => {
  const s = series();
  const near = smartPlaybackRow(ready({ ...s, index: s.index.map((i) => i * 2) }), 11);
  assert.ok(near.lines.some((l) => /frame 11 .*nearest stored point/.test(l)), near.lines.join("\n"));
  const stale = smartPlaybackRow(ready({ ...s, stale: true }), 5);
  assert.ok(stale.lines.some((l) => /stale/.test(l)));
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
