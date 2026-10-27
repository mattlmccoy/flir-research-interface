import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parseSmartOver, smartChip, smartDetails, smartEntryFromFeed, smartSummary, type SmartOver, type SmartReadoutEntry } from "./smartReadout.ts";
import { smartFeedFrom, smartRowView } from "./smartFeed.ts";
import { downsampleSmartSeries, parseSmartSeries, smartPlaybackRow, type SmartSeries } from "./smartSeries.ts";
import { smartTraces } from "./smartTraces.ts";

// Real backend output for six real A70 frames of 20261020_144402_Run (frames 18780, 18788, 18789,
// 18820, 18845, 18850, ~626 s): in rows 2-4 one, six and two sample pixels wrapped past the
// -20…250 °C case. `live[i]` = the live overlay (SmartLive.overlays, with the case ceiling) and the
// TC-POWER feed payload at that frame; `series` = GET …/smart-roi/113 of a recording of them.
// Captured by scripts/capture_smart_series_fixture.py --only overrange.
type Live = { index: number; overlay: Record<string, unknown> & { state: "locked"; valid: boolean; over?: unknown }; feed: { live: boolean; rois: Record<string, unknown>[] } };
const FX = JSON.parse(readFileSync(new URL("./fixtures/smart_overrange_20261020.json", import.meta.url), "utf8")) as { series: Record<string, unknown>; live: Live[] };
const unpad = (s: string): string => s.replace(/ /g, "");
const feedAt = (i: number) => smartFeedFrom(FX.live[i].feed, 10_000);
const overAt = (i: number): SmartOver => {
  const o = parseSmartOver(FX.live[i].overlay.over);
  assert.ok(o, `frame ${i} overlay has an over block`);
  return o;
};
const OVER_6 = "locked · mean ≥ 153 °C · min 114 · max > 250 (over range)";
const series = (patch: (raw: Record<string, unknown>) => void = () => {}): SmartSeries => {
  const raw = structuredClone(FX.series);
  patch(raw);
  const s = parseSmartSeries(raw);
  assert.ok(s, "the captured series parses");
  return s;
};

test("the real feed stays the TC-POWER contract: over-range = invalid, no numbers", () => {
  const e = smartEntryFromFeed(FX.live[3].feed.rois[0]);
  assert.ok(e);
  assert.equal(e.valid, false);
  assert.equal(e.over_range, true);
  assert.equal(e.sample.mean_c, null);
});

test("parseSmartOver: the real overlay block; anything malformed is null (never a partial number)", () => {
  const o = overAt(3);
  assert.equal(o.sample.over_px, 6);
  assert.equal(o.sample.max_c, null);
  assert.equal(o.sample.min_is_bound, false);
  assert.ok(Math.abs((o.sample.mean_lb_c ?? 0) - 152.63776452384792) < 1e-9);
  assert.equal(o.rings.length, 3);
  assert.equal(parseSmartOver(undefined), null);
  assert.equal(parseSmartOver({ sample: { ...(FX.live[3].overlay.over as { sample: object }).sample, over_px: "6" }, rings: [] }), null);
  assert.equal(parseSmartOver({ sample: null, rings: [] }), null);
});

test("live row: over-range numbers come from the frame's overlay, in the over tone", () => {
  const v = smartRowView(feedAt(3), 113, 10_000, 500, FX.live[3].overlay);
  assert.equal(unpad(v.summary), OVER_6);
  assert.equal(v.tone, "over");
  assert.equal(v.mean, null, "a lower bound is never the plotted / value-column mean");
  assert.equal(v.marker, "over range");
  assert.ok(v.entry?.over);
});

test("live row: without the overlay block the over-range row keeps today's numberless status", () => {
  const v = smartRowView(feedAt(3), 113, 10_000, 500);
  assert.equal(v.summary, "locked · not valid (over-range pixels)");
  assert.equal(v.tone, "invalid");
});

test("live row: a clean frame is the feed's plain locked reading", () => {
  const v = smartRowView(feedAt(0), 113, 10_000, 500, FX.live[0].overlay);
  assert.equal(v.tone, "locked");
  assert.ok(v.mean !== null && Math.abs(v.mean - (FX.live[0].feed.rois[0].mean_c as number)) < 1e-9);
});

test("live row: a stale or not-live feed never shows the overlay's numbers", () => {
  assert.equal(smartRowView(feedAt(3), 113, 20_000, 500, FX.live[3].overlay).tone, "none");
  const notLive = smartFeedFrom({ ...FX.live[3].feed, live: false }, 10_000);
  assert.equal(smartRowView(notLive, 113, 10_000, 500, FX.live[3].overlay).tone, "none");
});

test("over-range summary keeps one shape frame to frame (1, 6 and 2 pixels over)", () => {
  const lens = [2, 3, 4].map((i) => smartRowView(feedAt(i), 113, 10_000, 500, FX.live[i].overlay).summary.length);
  assert.deepEqual(new Set(lens).size, 1, `lengths ${lens}`);
});

const overEntry = (i: number, over: SmartOver = overAt(i)): SmartReadoutEntry => {
  const e = smartEntryFromFeed(FX.live[i].feed.rois[0]);
  assert.ok(e);
  return { ...e, over };
};

test("details: bounded sample, over-range px, rings with their own numbers", () => {
  const rows = smartDetails(overEntry(3)).map((r) => ({ label: r.label, value: unpad(r.value) }));
  assert.deepEqual(rows, [
    { label: "sample", value: "mean ≥ 153 °C · min 114 · max > 250 (over range)" },
    { label: "over-range px", value: "6 px" },
    { label: "ring 0–5 px", value: "mean 97.6 °C · max 120 · min 72.2" },
    { label: "ring 5–10 px", value: "mean 70.2 °C · max 112 · min 44.9" },
    { label: "ring 10–25 px", value: "mean 41.5 °C · max 76.8 · min 28.4" },
  ]);
  assert.deepEqual(smartDetails(overEntry(3), [10]).map((r) => r.label).includes("ring 5–10 px"), false, "hidden ring left out");
});

test("all pixels over range: the min is a bound too; an unknown ceiling says so", () => {
  const o = overAt(3);
  const all: SmartOver = { ...o, sample: { ...o.sample, min_c: 250.00002, min_is_bound: true, mean_lb_c: 250.00002, ceiling_c: null } };
  assert.equal(unpad(smartSummary(overEntry(3, all))), "locked · mean ≥ 250 °C · min ≥ 250 · max over range");
  const ringOver: SmartOver = { ...o, rings: [{ ...o.rings[0], over_px: 3, max_c: null, mean_lb_c: 101.0 }, o.rings[1], o.rings[2]] };
  assert.equal(unpad(smartDetails(overEntry(3, ringOver))[2].value), "mean ≥ 101 °C · min 72.2 · max > 250 (over range) · 3 px");
});

test("chip: over-range reads in warn with the bound, never as a healthy reading", () => {
  const draw = { state: "locked" as const, valid: false, over: overAt(3) };
  assert.deepEqual(smartChip(draw, overEntry(3)), { value: "locked · over range", range: "mean ≥ 152.6  max > 250", muted: false, warn: true });
  assert.equal(smartChip({ state: "searching", valid: false, over: overAt(3) }, undefined).warn, undefined, "searching shows no numbers");
});

test("playback: stored over-range rows read like the live row; clean rows unchanged", () => {
  const st = { kind: "ready" as const, series: series() };
  const v = smartPlaybackRow(st, 3);
  assert.equal(unpad(v.summary), OVER_6);
  assert.equal(v.tone, "over");
  assert.equal(v.mean, null);
  assert.deepEqual(smartDetails(v.entry!).slice(0, 2).map((r) => unpad(r.value)), ["mean ≥ 153 °C · min 114 · max > 250 (over range)", "6 px"]);
  assert.equal(smartPlaybackRow(st, 0).tone, "locked");
});

test("playback: an older series without the over columns stays blank, with a recompute hint", () => {
  const s = series((raw) => { delete raw.over; });
  assert.equal(s.over, null);
  const v = smartPlaybackRow({ kind: "ready", series: s }, 3);
  assert.equal(v.summary, "locked · not valid (over-range pixels)");
  assert.equal(v.tone, "invalid");
  assert.ok(v.notes.some((n) => /recompute/.test(n) && /over range/.test(n)), v.notes.join(" | "));
  const older = series((raw) => { delete raw.over; delete raw.over_range; });
  assert.equal(smartPlaybackRow({ kind: "ready", series: older }, 3).summary, "locked · not valid");
});

test("plot: over-range rows draw the lower bound as its own warn trace joined to the mean", () => {
  const s = series();
  const roi = { id: 113, label: "cube", color: "var(--trace-3)" };
  const tr = smartTraces(s, { sample: true, rings: false, dims: "off" }, roi);
  assert.equal(tr.length, 2);
  const [mean, lb] = tr;
  assert.deepEqual([2, 3, 4].map((k) => Number.isNaN(mean.v[k])), [true, true, true], "the mean itself stays a gap");
  assert.equal(lb.label, "cube mean ≥ lower bound (over range)");
  assert.equal(lb.color, "var(--warn)");
  assert.ok(lb.dash && lb.dash.length > 0);
  assert.equal(lb.axis, "temp");
  assert.ok(Number.isNaN(lb.v[0]));
  assert.equal(lb.v[1], mean.v[1], "joins the last valid point before");
  assert.equal(lb.v[3], s.over!.sample.mean_lb[3]);
  assert.equal(lb.v[5], mean.v[5], "and the first one after");
  assert.equal(smartTraces(series((raw) => { delete raw.over; }), { sample: true, rings: false, dims: "off" }, roi).length, 1, "older series: no bound trace");
  assert.equal(smartTraces(downsampleSmartSeries(s, 3), { sample: true, rings: false, dims: "off" }, roi).length, 2, "downsampling keeps the columns");
});
