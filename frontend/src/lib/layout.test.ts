import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout, type LayoutState } from "./layout.ts";

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(), key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k),
  } as Storage;
}

test("defaults: strip and rail open, dock open, all rail sections open, tool select", () => {
  assert.equal(DEFAULT_LAYOUT.strip, true);
  assert.equal(DEFAULT_LAYOUT.rail, true);
  assert.equal(DEFAULT_LAYOUT.dock, true);
  assert.equal(DEFAULT_LAYOUT.tool, "select");
  assert.deepEqual(Object.values(DEFAULT_LAYOUT.sections).every(Boolean), true);
});

test("toggle actions flip one flag and leave the rest", () => {
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "toggle", panel: "rail" });
  assert.equal(s1.rail, false); assert.equal(s1.strip, true); assert.equal(s1.dock, true);
  const s2 = layoutReducer(s1, { type: "toggleSection", section: "camera" });
  assert.equal(s2.sections.camera, false); assert.equal(s2.sections.measurements, true);
});

test("setTool changes the active tool", () => {
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setTool", tool: "rect" }).tool, "rect");
});

test("collapseAll hides strip, rail and dock; restore brings them back", () => {
  const c = layoutReducer(DEFAULT_LAYOUT, { type: "collapseAll" });
  assert.deepEqual([c.strip, c.rail, c.dock], [false, false, false]);
  const r = layoutReducer(c, { type: "restoreAll" });
  assert.deepEqual([r.strip, r.rail, r.dock], [true, true, true]);
});

test("save/load round-trips and ignores corrupt storage", () => {
  const st = memStorage();
  const s: LayoutState = { ...DEFAULT_LAYOUT, rail: false, tool: "spot" };
  saveLayout(st, s);
  assert.deepEqual(loadLayout(st), s);
  st.setItem("fri.layout.v1", "{not json");
  assert.deepEqual(loadLayout(st), DEFAULT_LAYOUT);
  assert.deepEqual(loadLayout(null), DEFAULT_LAYOUT);
});
