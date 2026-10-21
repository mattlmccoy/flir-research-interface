import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { smartBadge, smartChip, smartEntryFromFeed, smartFeedMap, smartReadoutLines, type SmartReadoutEntry } from "./smartReadout.ts";

// Real GET /api/live/roi-temps payloads (backend live_temps.live_roi_payload over the real live
// tracker SmartLive and five real A70 frames of run 20261020_144402_Run), captured by
// scripts/capture_smart_series_fixture.py --only feed. Locked = the 549 s frame, holding = the
// first frame after the sample vanished, searching = the first frame after HOLD_S lapsed.
type Payload = { rois: Record<string, unknown>[] };
const FEED = JSON.parse(readFileSync(new URL("./fixtures/smart_feed_20261020.json", import.meta.url), "utf8")) as Record<"locked" | "holding" | "searching", Payload>;
const FEED_LOCKED = FEED.locked.rois[0] as Record<string, unknown> & { rings: Record<string, unknown>[]; dims: Record<string, unknown> };
const FEED_HOLDING = FEED.holding.rois[0];
const FEED_SEARCHING = FEED.searching.rois[0];

const entry = (raw: unknown): SmartReadoutEntry => {
  const e = smartEntryFromFeed(raw);
  assert.ok(e, "feed entry should parse");
  return e;
};

test("locked: numbers, rings, thermal-edge size and change since first lock", () => {
  assert.deepEqual(smartReadoutLines(entry(FEED_LOCKED)), [
    "locked · mean 113 °C · max 147 · min 86.7 · area 1077 px",
    "ring 0–5 px · mean 72.5 °C · max 86.5 · min 53.2",
    "ring 5–10 px · mean 51.1 °C · max 73.1 · min 39.5",
    "ring 10–25 px · mean 33.7 °C · max 50.3 · min 26.8",
    "size (thermal edge, px) · length 41.6 · width 34.5 · perimeter 118 · sharpness 6.33 °C/px",
    "change since first lock · area +19.3 % · length +8.6 % · width −5.0 %",
    "centroid 60.5, 59.5 px",
  ]);
});

test("holding is valid: numbers shown, prefixed holding — edge lost", () => {
  const lines = smartReadoutLines(entry(FEED_HOLDING));
  assert.equal(lines[0], "holding — edge lost · mean 25.0 °C · max 25.0 · min 25.0 · area 1077 px");
  assert.equal(lines[1], "ring 0–5 px · mean 25.0 °C · max 25.0 · min 25.0");
  assert.equal(lines.length, 7);
});

test("searching (invalid): status text only, no numbers", () => {
  const e = entry(FEED_SEARCHING);
  assert.equal(e.valid, false);
  assert.equal(e.rings.length, 3, "the operator always sends one (null) ring per offset");
  assert.deepEqual(smartReadoutLines(e), ["searching… (not locked yet)"]);
});

test("invalid while locked or holding (e.g. over-range) never shows numbers", () => {
  // the operator keeps the state but drops the numbers (live_temps._smart_entry, invalid branch);
  // derived from the captured locked entry (the five real frames have no over-range pixels)
  const nullRings = FEED_LOCKED.rings.map((r) => ({ ...r, mean_c: null, max_c: null, min_c: null }));
  const over = { ...FEED_LOCKED, valid: false, over_range: true, mean_c: null, max_c: null, min_c: null, dims: null, rings: nullRings };
  assert.deepEqual(smartReadoutLines(entry(over)), ["locked · not valid (over-range pixels)"]);
  const lapsed = { ...over, state: "holding", over_range: false };
  assert.deepEqual(smartReadoutLines(entry(lapsed)), ["holding — edge lost · not valid"]);
});

test("missing values read n/a, never as a number", () => {
  const raw = { ...FEED_LOCKED,
    rings: [{ inner_px: 0, outer_px: 5, mean_c: null, max_c: null, min_c: null }],
    dims: { ...FEED_LOCKED.dims, sharpness_c_per_px: null, area_change_pct: null, length_change_pct: null, width_change_pct: null } };
  assert.deepEqual(smartReadoutLines(entry(raw)), [
    "locked · mean 113 °C · max 147 · min 86.7 · area 1077 px",
    "ring 0–5 px · n/a",
    "size (thermal edge, px) · length 41.6 · width 34.5 · perimeter 118 · sharpness n/a",
    "change since first lock · area n/a · length n/a · width n/a",
    "centroid 60.5, 59.5 px",
  ]);
});

test("a valid entry without dims shows no size lines", () => {
  assert.deepEqual(smartReadoutLines(entry({ ...FEED_LOCKED, rings: [], dims: null })), [
    "locked · mean 113 °C · max 147 · min 86.7",
  ]);
});

test("smartEntryFromFeed rejects anything that is not a smart feed entry", () => {
  assert.equal(smartEntryFromFeed(null), null);
  assert.equal(smartEntryFromFeed({ ...FEED_LOCKED, kind: "rect" }), null);
  assert.equal(smartEntryFromFeed({ ...FEED_LOCKED, state: "lost" }), null);
  // a "valid" entry without sample numbers is not trusted as valid
  assert.equal(smartEntryFromFeed({ ...FEED_LOCKED, mean_c: null })?.valid, false);
});

test("smartBadge is the spec §3 state text", () => {
  assert.equal(smartBadge("locked"), "locked");
  assert.equal(smartBadge("holding"), "holding — edge lost");
  assert.equal(smartBadge("searching"), "searching… (not locked yet)");
});

test("smartFeedMap keys the feed's smart entries by ROI id and skips everything else", () => {
  const payload = { live: true, rois: [
    { id: 1, kind: "rect", mean_c: 30, max_c: 31, min_c: 29, valid: true },
    FEED_LOCKED,
    { id: "x", kind: "smart", state: "locked", valid: true },
  ] };
  const m = smartFeedMap(payload);
  assert.deepEqual([...m.keys()], [3]);
  assert.equal(m.get(3)?.sample.mean_c, FEED_LOCKED.mean_c);
  assert.equal(smartFeedMap(null).size, 0);
  assert.equal(smartFeedMap({ rois: "nope" }).size, 0);
});

test("a change that rounds to zero reads +0.0 %, never −0.0 %", () => {
  const raw = { ...FEED_LOCKED, dims: { ...FEED_LOCKED.dims, area_change_pct: -0.04, length_change_pct: -0.0, width_change_pct: 0.04 } };
  assert.equal(smartReadoutLines(entry(raw))[5], "change since first lock · area +0.0 % · length +0.0 % · width +0.0 %");
});

test("smartChip: state from the frame's overlay, numbers only when the feed agrees and is valid", () => {
  const locked = entry(FEED_LOCKED);
  assert.deepEqual(smartChip({ state: "locked", valid: true }, locked), { value: "locked", range: "mean 113.4  max 147.4", muted: false });
  assert.equal(smartChip({ state: "locked", valid: true }, locked).muted, false, "valid: ROI colour dot");
  assert.equal(smartChip({ state: "searching", valid: false }, locked).muted, true, "searching: muted dot");
  assert.equal(smartChip({ state: "locked", valid: false }, undefined).muted, true, "invalid: muted dot");
  assert.equal(smartChip(undefined, undefined).muted, true);
  // the feed (polled) lags the frame stream: never pair the frame's state with another state's numbers
  assert.deepEqual(smartChip({ state: "searching", valid: false }, locked), { value: "searching… (not locked yet)", range: null, muted: true });
  assert.deepEqual(smartChip({ state: "holding", valid: true }, undefined), { value: "holding — edge lost", range: null, muted: false });
  assert.deepEqual(smartChip({ state: "locked", valid: false }, undefined), { value: "locked · not valid", range: null, muted: true });
  assert.deepEqual(smartChip(undefined, locked), { value: "locked", range: "mean 113.4  max 147.4", muted: false }, "no overlay: the feed alone");
  assert.deepEqual(smartChip(undefined, undefined), { value: "no outline", range: null, muted: true });
});
