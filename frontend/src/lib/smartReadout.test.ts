import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { smartBadge, smartChip, smartDetails, smartEntryFromFeed, smartFeedMap, smartReadoutLines, smartSummary, type SmartReadoutEntry } from "./smartReadout.ts";

// Real GET /api/live/roi-temps payloads (backend live_temps.live_roi_payload over the real live
// tracker SmartLive and five real A70 frames of run 20261020_144402_Run), captured by
// scripts/capture_smart_series_fixture.py --only feed. Locked = the 549 s frame, holding = the
// first frame after the sample vanished, searching = the first frame after HOLD_S lapsed.
type Payload = { rois: Record<string, unknown>[] };
const FEED = JSON.parse(readFileSync(new URL("./fixtures/smart_feed_20261020.json", import.meta.url), "utf8")) as Record<"locked" | "holding" | "searching", Payload>;
const FEED_LOCKED = FEED.locked.rois[0] as Record<string, unknown> & { rings: Record<string, unknown>[]; dims: Record<string, unknown> };
const FEED_HOLDING = FEED.holding.rois[0];
const FEED_SEARCHING = FEED.searching.rois[0];

const unpad = (s: string): string => s.replace(/\u2007/g, "");  // figure-space padding (fixed row shape)
const entry = (raw: unknown): SmartReadoutEntry => {
  const e = smartEntryFromFeed(raw);
  assert.ok(e, "feed entry should parse");
  return e;
};

test("locked: numbers, rings, thermal-edge size and change since first lock", () => {
  assert.deepEqual(smartReadoutLines(entry(FEED_LOCKED)), [
    "locked · mean 111 °C · max 147 · min 82.4 · area 1172 px",
    "ring 0–5 px · mean 68.9 °C · max 82.3 · min 51.2",
    "ring 5–10 px · mean 48.7 °C · max 64.2 · min 38.1",
    "ring 10–25 px · mean 33.1 °C · max 48.4 · min 26.7",
    "size (thermal edge, px) · length 42.8 · width 35.6 · perimeter 119 · sharpness 6.20 °C/px",
    "change since first lock · area +13.3 % · length +7.6 % · width −5.9 %",
    "centroid 60.4, 59.4 px",
  ]);
});

test("holding is valid: numbers shown, prefixed holding — edge lost", () => {
  const lines = smartReadoutLines(entry(FEED_HOLDING));
  assert.equal(lines[0], "holding — edge lost · mean 25.0 °C · max 25.0 · min 25.0 · area 1172 px");
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
    "locked · mean 111 °C · max 147 · min 82.4 · area 1172 px",
    "ring 0–5 px · n/a",
    "size (thermal edge, px) · length 42.8 · width 35.6 · perimeter 119 · sharpness n/a",
    "change since first lock · area n/a · length n/a · width n/a",
    "centroid 60.4, 59.4 px",
  ]);
});

test("a valid entry without dims shows no size lines", () => {
  assert.deepEqual(smartReadoutLines(entry({ ...FEED_LOCKED, rings: [], dims: null })), [
    "locked · mean 111 °C · max 147 · min 82.4",
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
  assert.deepEqual(smartChip({ state: "locked", valid: true }, locked), { value: "locked", range: "mean 111.0  max 147.4", muted: false });
  assert.equal(smartChip({ state: "locked", valid: true }, locked).muted, false, "valid: ROI colour dot");
  assert.equal(smartChip({ state: "searching", valid: false }, locked).muted, true, "searching: muted dot");
  assert.equal(smartChip({ state: "locked", valid: false }, undefined).muted, true, "invalid: muted dot");
  assert.equal(smartChip(undefined, undefined).muted, true);
  // the feed (polled) lags the frame stream: never pair the frame's state with another state's numbers
  assert.deepEqual(smartChip({ state: "searching", valid: false }, locked), { value: "searching… (not locked yet)", range: null, muted: true });
  assert.deepEqual(smartChip({ state: "holding", valid: true }, undefined), { value: "holding — edge lost", range: null, muted: false });
  assert.deepEqual(smartChip({ state: "locked", valid: false }, undefined), { value: "locked · not valid", range: null, muted: true });
  assert.deepEqual(smartChip(undefined, locked), { value: "locked", range: "mean 111.0  max 147.4", muted: false }, "no overlay: the feed alone");
  assert.deepEqual(smartChip(undefined, undefined), { value: "no outline", range: null, muted: true });
});

test("smartChip: a stale stored outline (playback) is muted and says stale, never shows numbers", () => {
  const locked = entry(FEED_LOCKED);
  assert.deepEqual(smartChip({ state: "locked", valid: true, stale: true }, locked), { value: "locked · stale", range: null, muted: true });
  assert.deepEqual(smartChip({ state: "holding", valid: true, stale: true }, undefined), { value: "holding — edge lost · stale", range: null, muted: true });
  assert.deepEqual(smartChip({ state: "locked", valid: true, stale: false }, locked).muted, false);
});

// --- the rail row: one collapsed line, and a compact table when expanded ---

test("smartSummary: one line, state · mean · max · area", () => {
  assert.equal(unpad(smartSummary(entry(FEED_LOCKED))), "locked · 111 °C · max 147 · area 1172 px");
  assert.equal(unpad(smartSummary(entry(FEED_HOLDING))), "holding — edge lost · 25.0 °C · max 25.0 · area 1172 px");
  assert.equal(unpad(smartSummary(entry({ ...FEED_LOCKED, dims: null }))), "locked · 111 °C · max 147", "no dims, no area");
});

test("smartSummary: not valid reads the badge only, never a number", () => {
  assert.equal(smartSummary(entry(FEED_SEARCHING)), "searching… (not locked yet)");
  const over = { ...FEED_LOCKED, valid: false, over_range: true, mean_c: null, max_c: null, min_c: null, dims: null };
  assert.equal(smartSummary(entry(over)), "locked · not valid (over-range pixels)");
  assert.doesNotMatch(smartSummary(entry({ ...FEED_LOCKED, valid: false })), /\d/, "the operator said not valid: no numbers even if sent");
});

test("smartDetails: sample, each ring, size, sharpness, change and centroid as label/value rows", () => {
  assert.deepEqual(smartDetails(entry(FEED_LOCKED)), [
    { label: "sample", value: "mean 111 °C · max 147 · min 82.4" },
    { label: "ring 0–5 px", value: "mean 68.9 °C · max 82.3 · min 51.2" },
    { label: "ring 5–10 px", value: "mean 48.7 °C · max 64.2 · min 38.1" },
    { label: "ring 10–25 px", value: "mean 33.1 °C · max 48.4 · min 26.7" },
    { label: "length (edge)", value: "42.8 px" },
    { label: "width (edge)", value: "35.6 px" },
    { label: "perimeter", value: "119 px" },
    { label: "sharpness", value: "6.20 °C/px" },
    { label: "Δ area", value: "+13.3 %" },
    { label: "Δ length", value: "+7.6 %" },
    { label: "Δ width", value: "−5.9 %" },
    { label: "centroid", value: "60.4, 59.4 px" },
  ]);
});

test("smartDetails leaves hidden rings out (keyed by the ring's outer offset)", () => {
  const labels = smartDetails(entry(FEED_LOCKED), [5, 25]).map((r) => r.label);
  assert.deepEqual(labels.filter((l) => l.startsWith("ring")), ["ring 5–10 px"]);
});

test("smartDetails: not valid has no rows; missing dims give no size rows", () => {
  assert.deepEqual(smartDetails(entry(FEED_SEARCHING)), []);
  assert.deepEqual(smartDetails(entry({ ...FEED_LOCKED, rings: [], dims: null })), [{ label: "sample", value: "mean 111 °C · max 147 · min 82.4" }]);
});

test("flicker: consecutive locked summaries keep one fixed shape (same length, separators in place)", () => {
  const at = (mean: number, max: number, area: number) => smartSummary(entry({ ...FEED_LOCKED, mean_c: mean, max_c: max, dims: { ...FEED_LOCKED.dims, area_px: area } }));
  const lines = [at(99.94, 99.96, 998), at(99.96, 100.4, 1004), at(100.4, 101.2, 1010), at(9.5, 12.25, 87)];
  const shape = (s: string) => s.replace(/[0-9.  ]/g, "#");
  assert.deepEqual(new Set(lines.map((l) => l.length)).size, 1, lines.join("\n"));
  assert.equal(new Set(lines.map(shape)).size, 1, lines.join("\n"));
});
