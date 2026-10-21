import { test } from "node:test";
import assert from "node:assert/strict";
import { NEUTRAL_ADJUST, adjustLinear, type VisibleAdjust } from "./visibleAdjust.ts";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout } from "./layout.ts";
import {
  cachedRangeProbe,
  effectiveRange,
  filterTableValues,
  parseRangeHeader,
  rangeNote,
  recordStamp,
  recordedAdjust,
  sourceNote,
  svgFilterId,
} from "./visibleAdjustUi.ts";

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(), key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k),
  } as Storage;
}

const LOOK: VisibleAdjust = { exposure_ev: -1.2, brightness: 0.05, contrast: 1.4 };

test("recordStamp names the preset when the live values equal it", () => {
  const s = recordStamp({ ...LOOK }, { name: "white powder", visible_adjust: { ...LOOK } });
  assert.deepEqual(s, { ...LOOK, preset: "white powder", based_on: null });
});

test("recordStamp says based_on when the live values were changed after applying the preset", () => {
  const s = recordStamp({ ...LOOK, contrast: 2 }, { name: "white powder", visible_adjust: { ...LOOK } });
  assert.deepEqual(s, { ...LOOK, contrast: 2, preset: null, based_on: "white powder" });
});

test("recordStamp without a preset carries the values and no labels", () => {
  assert.deepEqual(recordStamp({ ...LOOK }, null), { ...LOOK, preset: null, based_on: null });
});

test("filterTableValues gives the model's slope and intercept exactly", () => {
  for (const a of [NEUTRAL_ADJUST, LOOK, { exposure_ev: 3, brightness: -0.5, contrast: 0.25 }, { exposure_ev: -3, brightness: 0.5, contrast: 4 }]) {
    const f = filterTableValues(a);
    const m = adjustLinear(a);
    assert.equal(Number(f.slope), m.slope);
    assert.equal(Number(f.intercept), m.intercept);
  }
});

test("svgFilterId is a plain id, the same for the same map and different for a different one", () => {
  const id = svgFilterId(LOOK);
  assert.match(id, /^[A-Za-z][A-Za-z0-9_-]*$/);
  assert.equal(svgFilterId({ ...LOOK }), id);
  assert.notEqual(svgFilterId({ ...LOOK, brightness: -0.05 }), id);
  assert.notEqual(svgFilterId({ ...LOOK, exposure_ev: 1.2 }), id);
});

test("rangeNote has three states: full is quiet, raw-untagged warns, unknown is not confirmed", () => {
  assert.equal(rangeNote("full"), null);
  assert.equal(rangeNote("raw-untagged"), "visible video shown without range correction");
  assert.equal(rangeNote(null), "range correction not confirmed");
  assert.equal(rangeNote(undefined), "range correction not confirmed");
});

test("effectiveRange: the header decides; the prediction counts only while the probe is pending", () => {
  assert.equal(effectiveRange(undefined, "full"), "full"); // pending: the info's prediction
  assert.equal(effectiveRange(undefined, null), null); // pending, no prediction: unknown
  assert.equal(effectiveRange(undefined, undefined), null);
  assert.equal(effectiveRange({ range: "raw-untagged" }, "full"), "raw-untagged");
  assert.equal(effectiveRange({ range: "full" }, "raw-untagged"), "full");
  assert.equal(effectiveRange({ range: null }, "full"), null); // probe failed / no header: unknown, never healthy
});

test("cachedRangeProbe keeps a successful header read and retries after a failure", async () => {
  const cache = new Map<string, Promise<"full" | "raw-untagged" | null>>();
  let calls = 0;
  const ok = async () => { calls += 1; return "full"; };
  assert.equal(await cachedRangeProbe(cache, "/a", ok), "full");
  assert.equal(await cachedRangeProbe(cache, "/a", ok), "full");
  assert.equal(calls, 1);

  calls = 0;
  const noHeader = async () => { calls += 1; return null; };
  assert.equal(await cachedRangeProbe(cache, "/b", noHeader), null);
  assert.equal(cache.has("/b"), false);
  assert.equal(await cachedRangeProbe(cache, "/b", noHeader), null);
  assert.equal(calls, 2);

  calls = 0;
  const throws = async (): Promise<string | null> => { calls += 1; throw new Error("network"); };
  assert.equal(await cachedRangeProbe(cache, "/c", throws), null);
  assert.equal(cache.has("/c"), false);
  assert.equal(calls, 1);
  assert.equal(await cachedRangeProbe(cache, "/c", ok), "full"); // the retry reads the header
  assert.equal(calls, 2);
  assert.equal(cache.has("/c"), true);
});

test("parseRangeHeader accepts only the two values the operator sends", () => {
  assert.equal(parseRangeHeader("full"), "full");
  assert.equal(parseRangeHeader(" raw-untagged "), "raw-untagged");
  assert.equal(parseRangeHeader(null), null);
  assert.equal(parseRangeHeader("corrected"), null);
});

test("recordedAdjust reads a valid metadata stamp and rejects an invalid one (like the backend)", () => {
  assert.deepEqual(recordedAdjust({ ...LOOK, preset: "p", based_on: null }), LOOK);
  assert.equal(recordedAdjust(null), null);
  assert.equal(recordedAdjust(undefined), null);
  assert.equal(recordedAdjust({ exposure_ev: 9, brightness: 0, contrast: 1 }), null, "out of range");
  assert.equal(recordedAdjust({ exposure_ev: 0, brightness: 0 }), null, "missing control");
  assert.equal(recordedAdjust({ exposure_ev: "1", brightness: 0, contrast: 1 }), null, "not a number");
});

test("sourceNote says where the shown adjustment comes from", () => {
  assert.equal(sourceNote("sidecar"), "saved for this run");
  assert.equal(sourceNote("recorded"), "as recorded");
  assert.equal(sourceNote("neutral"), "no adjustment");
});

test("layout: the live visible adjustment defaults to neutral and round-trips through storage", () => {
  assert.deepEqual(DEFAULT_LAYOUT.visibleAdjust, NEUTRAL_ADJUST);
  const st = memStorage();
  const s = layoutReducer(DEFAULT_LAYOUT, { type: "setVisibleAdjust", adjust: LOOK });
  assert.deepEqual(s.visibleAdjust, LOOK);
  saveLayout(st, s);
  const back = loadLayout(st);
  assert.deepEqual(back.visibleAdjust, LOOK);
  assert.equal(back.visibleMode, s.visibleMode, "other keys unaffected");
  assert.deepEqual(back.overlay, s.overlay);
});

test("layout: setVisibleAdjust clamps to the model's limits", () => {
  const s = layoutReducer(DEFAULT_LAYOUT, { type: "setVisibleAdjust", adjust: { exposure_ev: 9, brightness: -2, contrast: 0 } });
  assert.deepEqual(s.visibleAdjust, { exposure_ev: 3, brightness: -0.5, contrast: 0.25 });
});

test("layout: a garbage stored visibleAdjust falls back to neutral, the rest of the layout survives", () => {
  for (const bad of ["junk", 7, null, [1, 2, 3], { exposure_ev: "x", brightness: null, contrast: Number.NaN }]) {
    const st = memStorage();
    st.setItem("fri.layout.v1", JSON.stringify({ visibleMode: "side", visibleAdjust: bad }));
    const l = loadLayout(st);
    assert.deepEqual(l.visibleAdjust, NEUTRAL_ADJUST, JSON.stringify(bad));
    assert.equal(l.visibleMode, "side");
  }
  const st = memStorage();
  st.setItem("fri.layout.v1", JSON.stringify({ visibleAdjust: { exposure_ev: 99, brightness: 0.1, contrast: 2 } }));
  assert.deepEqual(loadLayout(st).visibleAdjust, { exposure_ev: 3, brightness: 0.1, contrast: 2 }, "out of range is clamped");
});

test("layout: a layout saved before this feature loads with a neutral adjustment", () => {
  const st = memStorage();
  st.setItem("fri.layout.v1", JSON.stringify({ visibleMode: "overlay", rail: false }));
  const l = loadLayout(st);
  assert.deepEqual(l.visibleAdjust, NEUTRAL_ADJUST);
  assert.equal(l.visibleMode, "overlay");
  assert.equal(l.rail, false);
});
