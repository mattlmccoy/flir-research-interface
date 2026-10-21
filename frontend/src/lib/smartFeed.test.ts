import assert from "node:assert/strict";
import { test } from "node:test";
import { feedFresh, smartFeedFrom, smartRowView, type SmartFeed } from "./smartFeed.ts";

// GET /api/live/roi-temps shape (backend analysis/live_temps.py): {live, stale, rois:[...]}
const LOCKED = {
  id: 3, kind: "smart", mean_c: 507.3, max_c: 522.1, min_c: 480.4, over_range: false, valid: true, state: "locked",
  rings: [], dims: null,
};
const payload = (over: Record<string, unknown> = {}, live = true) => ({ live, stale: !live, rois: [{ ...LOCKED, ...over }] });

test("feedFresh: a feed older than two poll intervals (or failed) is not fresh", () => {
  const f = smartFeedFrom(payload(), 10_000);
  assert.equal(feedFresh(f, 10_000, 500), true);
  assert.equal(feedFresh(f, 11_000, 500), true);
  assert.equal(feedFresh(f, 11_001, 500), false, "hung poll: last good numbers must not stay up");
  const failed: SmartFeed = { ok: false, at: 10_000, live: false, entries: new Map() };
  assert.equal(feedFresh(failed, 10_000, 500), false);
  assert.equal(feedFresh(null, 10_000, 500), false);
});

test("smartRowView: a stale feed reads unreachable, never the last numbers", () => {
  const f = smartFeedFrom(payload(), 0);
  const v = smartRowView(f, 3, 5_000, 500);
  assert.equal(v.mean, null);
  assert.equal(v.tone, "none");
  assert.deepEqual(v.lines, ["no reading: the operator's live feed is unreachable"]);
});

test("smartRowView: operator not live says so instead of searching", () => {
  const raw = { ...LOCKED, valid: false, state: "searching", mean_c: null, max_c: null, min_c: null };
  const f = smartFeedFrom({ live: false, stale: true, rois: [raw] }, 0);
  const v = smartRowView(f, 3, 0, 500);
  assert.deepEqual(v.lines, ["operator not live: no current camera frame"]);
  assert.equal(v.mean, null);
  assert.equal(v.tone, "none");
});

test("smartRowView: locked is live-toned with its mean; holding is warn-toned with a holding marker", () => {
  const l = smartRowView(smartFeedFrom(payload(), 0), 3, 0, 500);
  assert.equal(l.tone, "locked");
  assert.equal(l.mean, 507.3);
  assert.equal(l.marker, null);
  const h = smartRowView(smartFeedFrom(payload({ state: "holding" }), 0), 3, 0, 500);
  assert.equal(h.tone, "holding");
  assert.equal(h.mean, 507.3);
  assert.equal(h.marker, "holding");
  assert.match(h.lines[0], /^holding — edge lost · mean/);
});

test("smartRowView: searching / missing entry / no feed yet carry no number", () => {
  const s = smartRowView(smartFeedFrom(payload({ valid: false, state: "searching", mean_c: null }), 0), 3, 0, 500);
  assert.equal(s.mean, null);
  assert.equal(s.tone, "searching");
  assert.equal(s.marker, "searching");
  assert.deepEqual(smartRowView(smartFeedFrom(payload(), 0), 99, 0, 500).lines, ["no reading from the operator yet"]);
  assert.deepEqual(smartRowView(null, 3, 0, 500).lines, ["waiting for the operator…"]);
});

test("smartLiveValue: the live plot point is the operator's mean, NaN (a gap) whenever it is not a reading", async () => {
  const { smartLiveValue } = await import("./smartFeed.ts");
  assert.equal(smartLiveValue(smartFeedFrom(payload(), 0), 3, 0, 500), 507.3);
  assert.equal(smartLiveValue(smartFeedFrom(payload({ state: "holding" }), 0), 3, 0, 500), 507.3, "holding is valid");
  for (const [why, v] of [
    ["searching", smartLiveValue(smartFeedFrom(payload({ state: "searching", valid: false, mean_c: null, max_c: null, min_c: null }), 0), 3, 0, 500)],
    ["stale feed", smartLiveValue(smartFeedFrom(payload(), 0), 3, 5_000, 500)],
    ["not live", smartLiveValue(smartFeedFrom(payload({}, false), 0), 3, 0, 500)],
    ["no entry", smartLiveValue(smartFeedFrom(payload(), 0), 9, 0, 500)],
    ["no feed", smartLiveValue(null, 3, 0, 500)],
  ] as const) assert.ok(Number.isNaN(v), why);
});
