import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeTag, mergeTags, suggestTags, tagUniverse, filterExperiments, sortExperiments,
  selectionReducer, type SelectionState,
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
