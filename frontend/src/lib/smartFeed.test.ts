import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { feedFresh, smartFeedFrom, smartRowView, type SmartFeed } from "./smartFeed.ts";

// Real GET /api/live/roi-temps payloads (backend live_temps.live_roi_payload + SmartLive over real
// A70 frames), captured by scripts/capture_smart_series_fixture.py --only feed.
type Payload = { live: boolean; stale: boolean; rois: Record<string, unknown>[] };
const FEED = JSON.parse(readFileSync(new URL("./fixtures/smart_feed_20261020.json", import.meta.url), "utf8")) as Record<"locked" | "holding" | "searching", Payload>;
const LOCKED = FEED.locked.rois[0];
const MEAN = LOCKED.mean_c as number;
/** A captured payload; `over` patches its smart entry (for cases the real frames lack). */
const payload = (over: Record<string, unknown> = {}, live = true, base: Payload = FEED.locked) => ({ ...base, live, stale: !live, rois: [{ ...base.rois[0], ...over }] });

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
  assert.equal(v.summary, "no reading: the operator's live feed is unreachable");
  assert.equal(v.entry, null);
});

test("smartRowView: operator not live says so instead of searching", () => {
  const f = smartFeedFrom(payload({}, false, FEED.searching), 0);
  const v = smartRowView(f, 3, 0, 500);
  assert.equal(v.summary, "operator not live: no current camera frame");
  assert.equal(v.mean, null);
  assert.equal(v.tone, "none");
});

test("smartRowView: locked is live-toned with its mean; holding is warn-toned with a holding marker", () => {
  const l = smartRowView(smartFeedFrom(payload(), 0), 3, 0, 500);
  assert.equal(l.tone, "locked");
  assert.equal(l.mean, MEAN);
  assert.equal(l.marker, null);
  const h = smartRowView(smartFeedFrom(FEED.holding, 0), 3, 0, 500);
  assert.equal(h.tone, "holding");
  assert.equal(h.mean, 25.0);
  assert.equal(h.marker, "holding");
  assert.equal(h.summary.replace(/\u2007/g, ""), "holding — edge lost · 25.0 °C · max 25.0 · area 1172 px");
  assert.equal(h.entry?.state, "holding", "the expanded table reads the same entry");
  assert.match(l.summary.replace(/\u2007/g, ""), /^locked · \d+ °C · max \d+ · area \d+ px$/, "collapsed: one line");
});

test("smartRowView: searching / missing entry / no feed yet carry no number", () => {
  const s = smartRowView(smartFeedFrom(FEED.searching, 0), 3, 0, 500);
  assert.equal(s.mean, null);
  assert.equal(s.tone, "searching");
  assert.equal(s.marker, "searching");
  assert.equal(smartRowView(smartFeedFrom(payload(), 0), 99, 0, 500).summary, "no reading from the operator yet");
  assert.equal(smartRowView(null, 3, 0, 500).summary, "waiting for the operator…");
  assert.equal(s.summary, "searching… (not locked yet)");
});

test("smartLiveValue: the live plot point is the operator's mean, NaN (a gap) whenever it is not a reading", async () => {
  const { smartLiveValue } = await import("./smartFeed.ts");
  assert.equal(smartLiveValue(smartFeedFrom(payload(), 0), 3, 0, 500), MEAN);
  assert.equal(smartLiveValue(smartFeedFrom(FEED.holding, 0), 3, 0, 500), 25.0, "holding is valid");
  for (const [why, v] of [
    ["searching", smartLiveValue(smartFeedFrom(FEED.searching, 0), 3, 0, 500)],
    ["stale feed", smartLiveValue(smartFeedFrom(payload(), 0), 3, 5_000, 500)],
    ["not live", smartLiveValue(smartFeedFrom(payload({}, false), 0), 3, 0, 500)],
    ["no entry", smartLiveValue(smartFeedFrom(payload(), 0), 9, 0, 500)],
    ["no feed", smartLiveValue(null, 3, 0, 500)],
  ] as const) assert.ok(Number.isNaN(v), why);
});

test("smartChipFeed: the on-image chips get the feed's entries only while it is fresh and live", async () => {
  const { smartChipFeed } = await import("./smartFeed.ts");
  const f = smartFeedFrom(payload(), 10_000);
  assert.equal(smartChipFeed(f, 10_500, 500)?.get(3)?.sample.mean_c, MEAN);
  assert.equal(smartChipFeed(f, 11_001, 500), undefined, "hung poll: chips must not keep the last numbers");
  assert.equal(smartChipFeed(smartFeedFrom(payload({}, false), 10_000), 10_000, 500), undefined, "not live");
  assert.equal(smartChipFeed({ ok: false, at: 10_000, live: true, entries: f.entries }, 10_000, 500), undefined, "failed poll");
  assert.equal(smartChipFeed(null, 10_000, 500), undefined);
});
