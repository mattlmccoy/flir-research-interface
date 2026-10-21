import { test } from "node:test";
import assert from "node:assert/strict";
import { markColor, markerLegend, nextMarkerIndex } from "./events.ts";
import { markersWithFlashes, visibleFlashMarkers, visibleSampleIsError, visibleSampleStatusText, type VisibleSampleSummary } from "./visibleSample.ts";

// Event times, peaks, coverage and the segment's start are the values measured on the real run
// 20261020_144402_Run (task-3 report, `merge_s=1.0`; its exports/visible_sample.json). That file was
// written before `anchor` existed; "first_frame" is what thermal_segments gives that run (its segment
// has first_frame_host_ns). The surrounding keys follow `_summary` in visible_sample_run.py.
const OK: VisibleSampleSummary = {
  status: "ok",
  reason: null,
  coverage: { frames_analysed: 6189, t_first_s: 26.483, t_last_s: 632.572, gaps_over_300ms: 61 },
  events: [
    { t_start_s: 553.951, t_peak_s: 554.057, t_end_s: 554.057, peak_brightening: 20.0, n_frames: 2, peak_frame: 5303, segment: 0 },
    { t_start_s: 615.664, t_peak_s: 615.664, t_end_s: 615.846, peak_brightening: 19.0, n_frames: 2, peak_frame: 6005, segment: 0 },
    { t_start_s: 627.769, t_peak_s: 627.769, t_end_s: 629.411, peak_brightening: 97.0, n_frames: 7, peak_frame: 6142, segment: 0 },
  ],
  segments: [{ index: 0, file: "visible.mp4", t_start_s: 25.996, anchor: "first_frame", frames_analysed: 6189 }],
  missing: [],
  plot_error: null,
};
// Thermal frame times around each flash, captured from the real run's exports/roi_series.csv, plus the
// two marks that eventsToMarkers already places exactly on a frame (RF ON at 4.0 s, the gap at 261.054 s).
const TS = [
  4.0, 261.054,
  554.009, 554.042, 554.075, 554.108,
  615.61, 615.643, 615.676, 615.709,
  627.73, 627.763, 627.797, 627.83,
];
const SKIPPED: VisibleSampleSummary = { status: "skipped", reason: "no sample ROI is drawn" };
const FAILED: VisibleSampleSummary = { status: "failed", reason: "ValueError: visible segments are not in time order" };

test("one marker per event on the thermal frame nearest its peak, labelled with the rounded peak", () => {
  // peaks 554.057 -> frame 554.042, 615.664 -> 615.676, 627.769 -> 627.763
  assert.deepEqual(visibleFlashMarkers(OK, TS), [
    { t: 554.042, label: "visible flash +20" },
    { t: 615.676, label: "visible flash +19" },
    { t: 627.763, label: "visible flash +97" },
  ]);
});

test("the marker label rounds a fractional peak", () => {
  const vs: VisibleSampleSummary = { ...OK, events: [{ ...OK.events![0], peak_brightening: 19.6 }] };
  assert.equal(visibleFlashMarkers(vs, TS)[0].label, "visible flash +20");
});

test("a skipped, failed or absent run has no markers", () => {
  assert.deepEqual(visibleFlashMarkers(SKIPPED, TS), []);
  assert.deepEqual(visibleFlashMarkers(FAILED, TS), []);
  assert.deepEqual(visibleFlashMarkers(null, TS), []);
  assert.deepEqual(visibleFlashMarkers(undefined, TS), []);
});

test("visible flash marks are coloured --trace-5 and get their own legend entry", () => {
  assert.equal(markColor("visible flash +97"), "var(--trace-5)");
  const legend = markerLegend(visibleFlashMarkers(OK, TS));
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

test("a segment timed from the ffmpeg launch says the visible times run about a second early", () => {
  const segments = [{ ...OK.segments![0], anchor: "launch" as const }];
  const text = visibleSampleStatusText({ ...OK, segments })!;
  assert.equal(
    text,
    "Visible sample: 3 flashes at the sample, 26.5–632.6 s analysed (61 gaps > 0.3 s); visible times from ffmpeg launch (~1 s early)",
  );
});

test("one launch-anchored segment among first-frame ones is enough to say so", () => {
  const second = { ...OK.segments![0], index: 1, file: "visible_001.mp4", anchor: "launch" as const };
  const text = visibleSampleStatusText({ ...OK, segments: [OK.segments![0], second] })!;
  assert.ok(text.includes("; visible times from ffmpeg launch (~1 s early)"), text);
});

test("segments timed from their first frame, or absent from the summary, add no timing note", () => {
  assert.ok(!visibleSampleStatusText(OK)!.includes("ffmpeg launch"));
  const { segments: _segments, ...noSegments } = OK;
  assert.ok(!visibleSampleStatusText(noSegments)!.includes("ffmpeg launch"));
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
  assert.deepEqual(visibleFlashMarkers({ ...OK, status: "running" } as unknown as VisibleSampleSummary, TS), []);
  assert.deepEqual(visibleFlashMarkers({} as unknown as VisibleSampleSummary, TS), []);
  assert.deepEqual(visibleFlashMarkers({ ...OK, events: {} } as unknown as VisibleSampleSummary, TS), []);
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

// -- placement on the thermal timeline ------------------------------------------------------------

// The whole marker set of the real run 20261020_144402_Run, as the playback page builds it. The
// flashes are snapped to frames (markersWithFlashes); `trigger` (0.0629 s) and `trigger_end` (627.0783 s)
// carry no frame_id, so eventsToMarkers places them at their wall-clock offset, BETWEEN frames. The
// frame times are captured from the run's exports/roi_series.csv (and the player's own landings);
// the first frame at 0.0 is the start of the recording. Labels are shape-only.
const WALK_TS = [
  0.0, 0.066,
  4.0, 4.029,
  261.054,
  554.009, 554.042, 554.075, 554.108,
  615.61, 615.643, 615.676, 615.709,
  627.031, 627.064, 627.097, 627.131,
  627.73, 627.763, 627.797, 627.83,
  631.06,
];
const WALK_BASE = [
  { t: 0.0629, label: "trigger" },
  { t: 4.029, label: "RF ON" },
  { t: 261.054, label: "gap 3" },
  { t: 627.0783, label: "trigger_end" },
  { t: 631.06, label: "RF OFF" },
];
const WALK_FORWARD = [0.066, 4.029, 261.054, 554.042, 615.676, 627.064, 627.763, 631.06];
const WALK_BACKWARD = [627.763, 627.064, 615.676, 554.042, 261.054, 4.029, 0.066];

/** Click ▶◆ (dir 1) or ◆◀ (dir -1) repeatedly from frame `index`; returns the frame times visited. */
function walkMarks(markers: { t: number; label: string }[], tS: number[], index: number, dir: 1 | -1, maxClicks = 12): number[] {
  const visited: number[] = [];
  let i = index;
  for (let click = 0; click < maxClicks; click++) {
    const next = nextMarkerIndex(markers, tS, i, dir);
    if (next === null) break;
    i = next;
    visited.push(tS[i]);
  }
  return visited;
}

test("▶◆ visits every mark of the real run in order, including the wall-clock-placed trigger_end", () => {
  const markers = markersWithFlashes(WALK_BASE, OK, WALK_TS);
  assert.deepEqual(walkMarks(markers, WALK_TS, 0, 1), WALK_FORWARD);
});

test("◆◀ visits every mark of the real run in reverse order", () => {
  const markers = markersWithFlashes(WALK_BASE, OK, WALK_TS);
  assert.deepEqual(walkMarks(markers, WALK_TS, WALK_TS.length - 1, -1), WALK_BACKWARD);
});

test("a non-finite peak time is dropped, not placed", () => {
  const events = [
    { ...OK.events![0], t_peak_s: NaN },
    { ...OK.events![1], t_peak_s: Infinity },
    { ...OK.events![2], t_peak_s: -Infinity },
    OK.events![2],
  ];
  assert.deepEqual(visibleFlashMarkers({ ...OK, events }, TS), [{ t: 627.763, label: "visible flash +97" }]);
});

test("a peak outside the recording's time span is dropped", () => {
  const events = [
    { ...OK.events![0], t_peak_s: 3.9 },    // before the first frame
    { ...OK.events![1], t_peak_s: 700.0 },  // after the last frame
    OK.events![2],
  ];
  assert.deepEqual(visibleFlashMarkers({ ...OK, events }, TS), [{ t: 627.763, label: "visible flash +97" }]);
});

test("a peak exactly on the first or last frame time is kept", () => {
  const events = [{ ...OK.events![0], t_peak_s: 4.0 }, { ...OK.events![2], t_peak_s: 627.83 }];
  assert.deepEqual(visibleFlashMarkers({ ...OK, events }, TS).map((m) => m.t), [4.0, 627.83]);
});

test("an empty timeline has nowhere to place a flash", () => {
  assert.deepEqual(visibleFlashMarkers(OK, []), []);
});

test("markersWithFlashes merges the flash marks into the event marks in time order", () => {
  const base = [{ t: 261.054, label: "gap 3" }, { t: 4.0, label: "RF ON" }, { t: 620.0, label: "RF OFF" }];
  assert.deepEqual(markersWithFlashes(base, OK, TS), [
    { t: 4.0, label: "RF ON" },
    { t: 261.054, label: "gap 3" },
    { t: 554.042, label: "visible flash +20" },
    { t: 615.676, label: "visible flash +19" },
    { t: 620.0, label: "RF OFF" },
    { t: 627.763, label: "visible flash +97" },
  ]);
});

test("markersWithFlashes leaves the event marks alone when there is nothing to add", () => {
  const base = [{ t: 4.0, label: "RF ON" }];
  assert.deepEqual(markersWithFlashes(base, null, TS), base);
  assert.deepEqual(markersWithFlashes(base, SKIPPED, TS), base);
  assert.notEqual(markersWithFlashes(base, null, TS), base, "returns a new array, never the input");
});
