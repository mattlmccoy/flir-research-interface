import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeTag, mergeTags, suggestTags, tagUniverse, filterExperiments, sortExperiments,
  selectionReducer, displayName, bulkTitles, type SelectionState,
} from "./organize.ts";

type E = { name: string; starred?: boolean; tags?: string[]; started_utc?: string | null };
const items: E[] = [
  { name: "b", starred: true, tags: ["Doped", "8020mix"], started_utc: "2026-09-02T00:00:00Z" },
  { name: "a", starred: false, tags: ["control"], started_utc: "2026-09-01T00:00:00Z" },
  { name: "c", starred: false, tags: [], started_utc: "2026-09-03T00:00:00Z" },
];

test("normalizeTag trims, collapses whitespace, caps length", () => {
  assert.equal(normalizeTag("  Doped  "), "Doped");
  assert.equal(normalizeTag("two   words"), "two words");
  assert.equal(normalizeTag(""), "");
  assert.equal(normalizeTag("x".repeat(60)).length, 40);
});

test("mergeTags dedupes case-insensitively, keeps first casing and order", () => {
  assert.deepEqual(mergeTags(["Doped"], ["doped", "new"]), ["Doped", "new"]);
});

test("tagUniverse counts and frequency-sorts", () => {
  const u = tagUniverse([{ tags: ["x", "y"] }, { tags: ["x"] }] as E[]);
  assert.deepEqual(u.map((t) => t.tag), ["x", "y"]);
  assert.equal(u[0].count, 2);
});

test("suggestTags: case-insensitive contains, excludes applied", () => {
  const s = suggestTags(["Doped", "control", "doped-batch2"], "dop", ["Doped"]);
  assert.deepEqual(s, ["doped-batch2"]);
});

test("filterExperiments matches name or tag, starred-only, AND over tags", () => {
  assert.deepEqual(filterExperiments(items, { query: "doped", starredOnly: false, tags: [] }).map((e) => e.name), ["b"]);
  assert.deepEqual(filterExperiments(items, { query: "", starredOnly: true, tags: [] }).map((e) => e.name), ["b"]);
  assert.deepEqual(filterExperiments(items, { query: "", starredOnly: false, tags: ["Doped", "8020mix"] }).map((e) => e.name), ["b"]);
  assert.deepEqual(filterExperiments(items, { query: "", starredOnly: false, tags: ["Doped", "control"] }).map((e) => e.name), []);
});

test("sortExperiments: starred first then newest", () => {
  assert.deepEqual(sortExperiments(items, "starred").map((e) => e.name), ["b", "c", "a"]);
  assert.deepEqual(sortExperiments(items, "newest").map((e) => e.name), ["c", "b", "a"]);
});

test("selectionReducer toggle/range/selectAll/clear", () => {
  let s: SelectionState = { anchor: null, selected: new Set<string>() };
  s = selectionReducer(s, { type: "toggle", name: "a" });
  assert.ok(s.selected.has("a"));
  s = selectionReducer(s, { type: "range", name: "c", order: ["a", "b", "c"] });
  assert.deepEqual([...s.selected].sort(), ["a", "b", "c"]);
  s = selectionReducer(s, { type: "selectAll", names: ["x", "y"] });
  assert.deepEqual([...s.selected].sort(), ["x", "y"]);
  s = selectionReducer(s, { type: "clear" });
  assert.equal(s.selected.size, 0);
});

test("search matches the display title and notes, not just the folder name", () => {
  const items = [
    { name: "20260911_121421_Run", title: "Doped coupon #3", notes: "load retuned at 40 s" },
    { name: "20260911_135955_Run" },
  ];
  const q = (query: string) => filterExperiments(items, { query, starredOnly: false, tags: [] }).map((e) => e.name);
  assert.deepEqual(q("coupon"), ["20260911_121421_Run"]);
  assert.deepEqual(q("RETUNED"), ["20260911_121421_Run"]);
  assert.deepEqual(q("135955"), ["20260911_135955_Run"]);  // folder name still searchable
});

test("name sort uses the display title when set, else the folder name", () => {
  const items = [
    { name: "20260911_A_Run", title: "zinc run" },
    { name: "20260911_B_Run", title: "alpha run" },
    { name: "20260911_C_Run" },
  ];
  assert.deepEqual(sortExperiments(items, "name").map((e) => displayName(e)),
    ["20260911_C_Run", "alpha run", "zinc run"]);
});

test("bulk titles: numbered in recording order, regardless of selection or screen order", () => {
  const picked = [
    { name: "20260911_150811_Run", started_utc: "2026-09-11T19:08:11Z" },
    { name: "20260911_121421_Run", started_utc: "2026-09-11T16:14:21Z" },
    { name: "20260911_135955_Run" },  // no started_utc: falls back to the timestamped folder name
  ];
  assert.deepEqual(bulkTitles(picked, "Doped coupon", true), [
    { name: "20260911_121421_Run", title: "Doped coupon 1" },
    { name: "20260911_135955_Run", title: "Doped coupon 2" },
    { name: "20260911_150811_Run", title: "Doped coupon 3" },
  ]);
});

test("bulk titles: unnumbered gives every run the same name; blank clears names", () => {
  const picked = [{ name: "b_Run" }, { name: "a_Run" }];
  assert.deepEqual(bulkTitles(picked, "  Warm-up  ", false).map((x) => x.title), ["Warm-up", "Warm-up"]);
  assert.deepEqual(bulkTitles(picked, "   ", true).map((x) => x.title), ["", ""]);  // "" = clear
  assert.deepEqual(bulkTitles([], "x", true), []);
});

test("bulk titles: zero-pads numbers so 10+ runs still sort by name", () => {
  const picked = Array.from({ length: 12 }, (_, i) => ({ name: `20261001_0000${String(i).padStart(2, "0")}_Run` }));
  const titles = bulkTitles(picked, "Sweep", true).map((x) => x.title);
  assert.equal(titles[0], "Sweep 01");
  assert.equal(titles[11], "Sweep 12");
});
