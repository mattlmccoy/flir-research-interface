import assert from "node:assert/strict";
import { test } from "node:test";
import { smartBadge, smartChip, smartEntryFromFeed, smartFeedMap, smartReadoutLines, type SmartReadoutEntry } from "./smartReadout.ts";

// Shape of a smart entry in GET /api/live/roi-temps (backend analysis/live_temps.py _smart_entry):
// flat mean_c/max_c/min_c plus state, valid, rings [{inner_px, outer_px, mean_c, max_c, min_c}]
// and dims (smart_roi.py _dims + *_change_pct).
const FEED_LOCKED = {
  id: 3, name: "graphite", kind: "smart",
  mean_c: 507.3, max_c: 522.1, min_c: 480.4, value_c: null, over_range: false, valid: true,
  state: "locked",
  rings: [
    { inner_px: 0, outer_px: 5, mean_c: 159.4, max_c: 170.2, min_c: 150.0 },
    { inner_px: 5, outer_px: 10, mean_c: 80.0, max_c: 90.0, min_c: 70.0 },
    { inner_px: 10, outer_px: 25, mean_c: 41.26, max_c: 45.0, min_c: 38.0 },
  ],
  dims: {
    area_px: 5697, length_px: 98.24, width_px: 61.0, perimeter_px: 310, centroid_x: 312.44, centroid_y: 240.06,
    sharpness_c_per_px: 4.123, area_change_pct: 1.24, length_change_pct: 0.4, width_change_pct: -0.31, units: "px",
  },
};

const entry = (raw: unknown): SmartReadoutEntry => {
  const e = smartEntryFromFeed(raw);
  assert.ok(e, "feed entry should parse");
  return e;
};

test("locked: numbers, rings, thermal-edge size and change since first lock", () => {
  assert.deepEqual(smartReadoutLines(entry(FEED_LOCKED)), [
    "locked · mean 507 °C · max 522 · min 480 · area 5697 px",
    "ring 0–5 px · mean 159 °C · max 170 · min 150",
    "ring 5–10 px · mean 80.0 °C · max 90.0 · min 70.0",
    "ring 10–25 px · mean 41.3 °C · max 45.0 · min 38.0",
    "size (thermal edge, px) · length 98.2 · width 61.0 · perimeter 310 · sharpness 4.12 °C/px",
    "change since first lock · area +1.2 % · length +0.4 % · width −0.3 %",
    "centroid 312.4, 240.1 px",
  ]);
});

test("holding is valid: numbers shown, prefixed holding — edge lost", () => {
  const lines = smartReadoutLines(entry({ ...FEED_LOCKED, state: "holding" }));
  assert.equal(lines[0], "holding — edge lost · mean 507 °C · max 522 · min 480 · area 5697 px");
  assert.equal(lines[1], "ring 0–5 px · mean 159 °C · max 170 · min 150");
  assert.equal(lines.length, 7);
});

test("searching (invalid): status text only, no numbers", () => {
  const raw = { ...FEED_LOCKED, state: "searching", valid: false, mean_c: null, max_c: null, min_c: null, dims: null,
    rings: FEED_LOCKED.rings.map((r) => ({ ...r, mean_c: null, max_c: null, min_c: null })) };
  assert.deepEqual(smartReadoutLines(entry(raw)), ["searching… (not locked yet)"]);
});

test("invalid while locked or holding (e.g. over-range) never shows numbers", () => {
  // the operator keeps the state but drops the numbers (live_temps._smart_entry, invalid branch)
  const over = { ...FEED_LOCKED, valid: false, over_range: true, mean_c: null, max_c: null, min_c: null, dims: null };
  assert.deepEqual(smartReadoutLines(entry(over)), ["locked · not valid (over-range pixels)"]);
  const lapsed = { ...over, state: "holding", over_range: false };
  assert.deepEqual(smartReadoutLines(entry(lapsed)), ["holding — edge lost · not valid"]);
});

test("missing values read n/a, never as a number", () => {
  const raw = { ...FEED_LOCKED,
    rings: [{ inner_px: 0, outer_px: 5, mean_c: null, max_c: null, min_c: null }],
    dims: { ...FEED_LOCKED.dims, sharpness_c_per_px: null, area_change_pct: null, length_change_pct: null, width_change_pct: null } };
  assert.deepEqual(smartReadoutLines(entry(raw)), [
    "locked · mean 507 °C · max 522 · min 480 · area 5697 px",
    "ring 0–5 px · n/a",
    "size (thermal edge, px) · length 98.2 · width 61.0 · perimeter 310 · sharpness n/a",
    "change since first lock · area n/a · length n/a · width n/a",
    "centroid 312.4, 240.1 px",
  ]);
});

test("a valid entry without dims shows no size lines", () => {
  assert.deepEqual(smartReadoutLines(entry({ ...FEED_LOCKED, rings: [], dims: null })), [
    "locked · mean 507 °C · max 522 · min 480",
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
  assert.equal(m.get(3)?.sample.mean_c, 507.3);
  assert.equal(smartFeedMap(null).size, 0);
  assert.equal(smartFeedMap({ rois: "nope" }).size, 0);
});

test("a change that rounds to zero reads +0.0 %, never −0.0 %", () => {
  const raw = { ...FEED_LOCKED, dims: { ...FEED_LOCKED.dims, area_change_pct: -0.04, length_change_pct: -0.0, width_change_pct: 0.04 } };
  assert.equal(smartReadoutLines(entry(raw))[5], "change since first lock · area +0.0 % · length +0.0 % · width +0.0 %");
});

test("smartChip: state from the frame's overlay, numbers only when the feed agrees and is valid", () => {
  const locked = entry(FEED_LOCKED);
  assert.deepEqual(smartChip({ state: "locked", valid: true }, locked), { value: "locked", range: "mean 507.3  max 522.1" });
  // the feed (polled) lags the frame stream: never pair the frame's state with another state's numbers
  assert.deepEqual(smartChip({ state: "searching", valid: false }, locked), { value: "searching… (not locked yet)", range: null });
  assert.deepEqual(smartChip({ state: "holding", valid: true }, undefined), { value: "holding — edge lost", range: null });
  assert.deepEqual(smartChip({ state: "locked", valid: false }, undefined), { value: "locked · not valid", range: null });
  assert.deepEqual(smartChip(undefined, locked), { value: "locked", range: "mean 507.3  max 522.1" }, "no overlay: the feed alone");
  assert.deepEqual(smartChip(undefined, undefined), { value: "no outline", range: null });
});
