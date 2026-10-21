import { test } from "node:test";
import assert from "node:assert/strict";
import { markColor, markerLegend } from "./events.ts";
import { visibleFlashMarkers, visibleSampleIsError, visibleSampleStatusText, type VisibleSampleSummary } from "./visibleSample.ts";

// Event times, peaks and coverage are the values measured on the real run 20261020_144402_Run
// (task-3 report, `merge_s=1.0`); the surrounding keys follow `_summary` in visible_sample_run.py.
const OK: VisibleSampleSummary = {
  status: "ok",
  reason: null,
  coverage: { frames_analysed: 6189, t_first_s: 26.483, t_last_s: 632.572, gaps_over_300ms: 61 },
  events: [
    { t_start_s: 553.951, t_peak_s: 554.057, t_end_s: 554.057, peak_brightening: 20.0, n_frames: 2, peak_frame: 5303 },
    { t_start_s: 615.664, t_peak_s: 615.664, t_end_s: 615.846, peak_brightening: 19.0, n_frames: 2, peak_frame: 6005 },
    { t_start_s: 627.769, t_peak_s: 627.769, t_end_s: 629.411, peak_brightening: 97.0, n_frames: 7, peak_frame: 6142 },
  ],
  missing: [],
  plot_error: null,
};
const SKIPPED: VisibleSampleSummary = { status: "skipped", reason: "no sample ROI is drawn" };
const FAILED: VisibleSampleSummary = { status: "failed", reason: "ValueError: visible segments are not in time order" };

test("one marker per event at its peak time, labelled with the rounded peak", () => {
  assert.deepEqual(visibleFlashMarkers(OK), [
    { t: 554.057, label: "visible flash +20" },
    { t: 615.664, label: "visible flash +19" },
    { t: 627.769, label: "visible flash +97" },
  ]);
});

test("the marker label rounds a fractional peak", () => {
  const vs: VisibleSampleSummary = { ...OK, events: [{ ...OK.events![0], peak_brightening: 19.6 }] };
  assert.equal(visibleFlashMarkers(vs)[0].label, "visible flash +20");
});

test("a skipped, failed or absent run has no markers", () => {
  assert.deepEqual(visibleFlashMarkers(SKIPPED), []);
  assert.deepEqual(visibleFlashMarkers(FAILED), []);
  assert.deepEqual(visibleFlashMarkers(null), []);
  assert.deepEqual(visibleFlashMarkers(undefined), []);
});

test("visible flash marks are coloured --trace-5 and get their own legend entry", () => {
  assert.equal(markColor("visible flash +97"), "var(--trace-5)");
  const legend = markerLegend(visibleFlashMarkers(OK));
  assert.deepEqual(legend, [{ label: "visible flash", color: "var(--trace-5)" }]);
});

test("status text for an ok run with three flashes", () => {
  assert.equal(
    visibleSampleStatusText(OK),
    "Visible sample: 3 flashes at the sample, 26.5–632.6 s analysed (61 gaps > 0.3 s)",
  );
});

test("status text for an ok run with one flash is singular", () => {
  const vs: VisibleSampleSummary = { ...OK, events: [OK.events![0]] };
  assert.match(visibleSampleStatusText(vs)!, /^Visible sample: 1 flash at the sample, /);
});

test("status text for an ok run with zero events reads 0 flashes, not a bare 'none'", () => {
  const vs: VisibleSampleSummary = { ...OK, events: [] };
  assert.equal(
    visibleSampleStatusText(vs),
    "Visible sample: 0 flashes at the sample, 26.5–632.6 s analysed (61 gaps > 0.3 s)",
  );
});

test("an ok run that is missing a video segment says so", () => {
  const text = visibleSampleStatusText({ ...OK, missing: ["visible_001.mp4"] })!;
  assert.ok(text.includes("missing video: visible_001.mp4"), text);
  const two = visibleSampleStatusText({ ...OK, missing: ["visible_001.mp4", "visible_002.mp4"] })!;
  assert.ok(two.includes("missing video: visible_001.mp4, visible_002.mp4"), two);
});

test("an ok run whose plot was not drawn does not read as fully successful", () => {
  const text = visibleSampleStatusText({ ...OK, plot_error: "OSError: disk full" })!;
  assert.ok(text.includes("plot not drawn (OSError: disk full)"), text);
});

test("an ok run with nothing missing and a drawn plot has no warnings appended", () => {
  const text = visibleSampleStatusText(OK)!;
  assert.ok(!text.includes("missing video"), text);
  assert.ok(!text.includes("plot not drawn"), text);
});

test("a skipped run shows its reason", () => {
  assert.equal(visibleSampleStatusText(SKIPPED), "Visible sample: not analysed (no sample ROI is drawn)");
});

test("a failed run shows its reason", () => {
  assert.equal(
    visibleSampleStatusText(FAILED),
    "Visible sample: analysis failed (ValueError: visible segments are not in time order)",
  );
});

test("an absent summary has no status line", () => {
  assert.equal(visibleSampleStatusText(null), null);
  assert.equal(visibleSampleStatusText(undefined), null);
});

test("a skipped or failed run with a null reason still says why nothing was analysed", () => {
  assert.equal(visibleSampleStatusText({ status: "skipped", reason: null }), "Visible sample: not analysed (no reason recorded)");
  assert.equal(visibleSampleStatusText({ status: "failed", reason: null }), "Visible sample: analysis failed (no reason recorded)");
});

test("an ok summary without coverage is reported as incomplete rather than as a clean run", () => {
  const text = visibleSampleStatusText({ status: "ok", reason: null, events: [] })!;
  assert.ok(text.startsWith("Visible sample:"), text);
  assert.ok(text.includes("coverage unknown"), text);
});

// -- unreadable and empty summaries must never read as healthy -------------------------------------

// coverage() in analysis/visible_sample.py returns exactly this for no analysed frames (checked by
// running it: {"frames_analysed": 0, "t_first_s": null, "t_last_s": null, "gaps_over_300ms": 0}).
const NO_FRAMES = { frames_analysed: 0, t_first_s: null, t_last_s: null, gaps_over_300ms: 0 };
const NOTHING_TO_MEASURE = "Visible sample: 0 frames analysed, nothing to measure";

test("an ok run with no analysed frames (null bounds, as coverage() returns) does not throw", () => {
  const vs: VisibleSampleSummary = { ...OK, coverage: NO_FRAMES, events: [] };
  assert.equal(visibleSampleStatusText(vs), NOTHING_TO_MEASURE);
});

test("zero analysed frames reads as nothing to measure even if the bounds are numbers", () => {
  const vs: VisibleSampleSummary = { ...OK, coverage: { ...OK.coverage!, frames_analysed: 0 }, events: [] };
  assert.equal(visibleSampleStatusText(vs), NOTHING_TO_MEASURE);
});

test("a null bound alone is enough to report nothing to measure, not a crash", () => {
  const noFirst: VisibleSampleSummary = { ...OK, coverage: { ...OK.coverage!, t_first_s: null } };
  const noLast: VisibleSampleSummary = { ...OK, coverage: { ...OK.coverage!, t_last_s: null } };
  assert.equal(visibleSampleStatusText(noFirst), NOTHING_TO_MEASURE);
  assert.equal(visibleSampleStatusText(noLast), NOTHING_TO_MEASURE);
});

test("zero analysed frames still reports a missing video segment", () => {
  const text = visibleSampleStatusText({ ...OK, coverage: NO_FRAMES, events: [], missing: ["visible_000.mp4"] })!;
  assert.ok(text.startsWith(NOTHING_TO_MEASURE), text);
  assert.ok(text.includes("missing video: visible_000.mp4"), text);
});

test("a summary with no status is unreadable, not an ok run", () => {
  assert.equal(visibleSampleStatusText({} as unknown as VisibleSampleSummary), "Visible sample: unreadable result (status missing)");
});

test("a summary with a status this UI does not know is unreadable and names it", () => {
  const vs = { status: "running", reason: null } as unknown as VisibleSampleSummary;
  assert.equal(visibleSampleStatusText(vs), "Visible sample: unreadable result (status running)");
});

test("an ok summary without an events list is unreadable, not '0 flashes'", () => {
  const { events: _events, ...noEvents } = OK;
  assert.equal(visibleSampleStatusText(noEvents), "Visible sample: unreadable result (no events list)");
  const notAnArray = { ...OK, events: {} } as unknown as VisibleSampleSummary;
  assert.equal(visibleSampleStatusText(notAnArray), "Visible sample: unreadable result (no events list)");
});

test("no markers come from an unknown status or a malformed events list", () => {
  assert.deepEqual(visibleFlashMarkers({ ...OK, status: "running" } as unknown as VisibleSampleSummary), []);
  assert.deepEqual(visibleFlashMarkers({} as unknown as VisibleSampleSummary), []);
  assert.deepEqual(visibleFlashMarkers({ ...OK, events: {} } as unknown as VisibleSampleSummary), []);
});

test("failed and unreadable summaries are styled as errors; skipped, ok, empty and absent are not", () => {
  assert.equal(visibleSampleIsError(FAILED), true);
  assert.equal(visibleSampleIsError({} as unknown as VisibleSampleSummary), true);
  assert.equal(visibleSampleIsError({ status: "running", reason: null } as unknown as VisibleSampleSummary), true);
  const { events: _events, ...noEvents } = OK;
  assert.equal(visibleSampleIsError(noEvents), true);
  assert.equal(visibleSampleIsError(SKIPPED), false);
  assert.equal(visibleSampleIsError(OK), false);
  assert.equal(visibleSampleIsError({ ...OK, coverage: NO_FRAMES, events: [] }), false);
  assert.equal(visibleSampleIsError(null), false);
  assert.equal(visibleSampleIsError(undefined), false);
});
