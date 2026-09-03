import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout, studioClasses, type LayoutState } from "./layout.ts";

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(), key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k),
  } as Storage;
}

test("defaults: strip and rail open, dock open, all rail sections open except profile, tool select", () => {
  assert.equal(DEFAULT_LAYOUT.strip, true);
  assert.equal(DEFAULT_LAYOUT.rail, true);
  assert.equal(DEFAULT_LAYOUT.dock, true);
  assert.equal(DEFAULT_LAYOUT.tool, "select");
  const { profile, ...rest } = DEFAULT_LAYOUT.sections;
  assert.equal(profile, false, "profile & histogram starts collapsed to keep the rail short");
  assert.deepEqual(Object.values(rest).every(Boolean), true);
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

test("loadLayout rejects invalid shapes instead of trusting them", () => {
  const st = memStorage();
  st.setItem("fri.layout.v1", JSON.stringify({ tool: "wrench", strip: "yes", sections: { camera: "open" }, evil: 1 }));
  assert.deepEqual(loadLayout(st), DEFAULT_LAYOUT);
});

test("loadLayout keeps valid fields when others are missing or invalid", () => {
  const st = memStorage();
  st.setItem("fri.layout.v1", JSON.stringify({ rail: false, tool: "bogus", sections: { camera: false } }));
  const s = loadLayout(st);
  assert.equal(s.rail, false); assert.equal(s.tool, "select");
  assert.equal(s.sections.camera, false); assert.equal(s.sections.display, true);
});

test("reducer does not mutate its input", () => {
  const snapshot = structuredClone(DEFAULT_LAYOUT);
  layoutReducer(DEFAULT_LAYOUT, { type: "toggleSection", section: "camera" });
  assert.deepEqual(DEFAULT_LAYOUT, snapshot);
});

test("a throwing Storage never escapes", () => {
  const bad = { getItem() { throw new Error("SecurityError"); }, setItem() { throw new Error("QuotaExceeded"); } } as unknown as Storage;
  assert.deepEqual(loadLayout(bad), DEFAULT_LAYOUT);
  assert.doesNotThrow(() => saveLayout(bad, DEFAULT_LAYOUT));
});

test("studioClasses: all panels present and open yields the bare studio class", () => {
  const r = studioClasses(DEFAULT_LAYOUT, { page: false, hasStrip: true, hasRail: true, hasDock: true });
  assert.equal(r.className, "studio");
  assert.equal(r.showStrip, true); assert.equal(r.showRail, true); assert.equal(r.showDock, true);
});

test("studioClasses: page mode with only a rail hides strip and dock regardless of layout flags", () => {
  const r = studioClasses(DEFAULT_LAYOUT, { page: true, hasStrip: true, hasRail: true, hasDock: true });
  assert.equal(r.className, "studio page no-strip no-dock");
  assert.equal(r.showRail, true);
});

test("studioClasses: rail hidden by caller (no rail content) reports no-rail", () => {
  const r = studioClasses(DEFAULT_LAYOUT, { page: false, hasStrip: true, hasRail: false, hasDock: true });
  assert.match(r.className, /\bno-rail\b/);
  assert.equal(r.showRail, false);
});

test("studioClasses: strip content present but layout.strip closed reports no-strip", () => {
  const closed: LayoutState = { ...DEFAULT_LAYOUT, strip: false };
  const r = studioClasses(closed, { page: false, hasStrip: true, hasRail: true, hasDock: true });
  assert.match(r.className, /\bno-strip\b/);
  assert.equal(r.showStrip, false);
});

test("openSection opens a closed section and shows the rail; it never closes anything", () => {
  const closed = { ...DEFAULT_LAYOUT, rail: false, sections: { ...DEFAULT_LAYOUT.sections, camera: false } };
  const s = layoutReducer(closed, { type: "openSection", section: "camera" });
  assert.equal(s.rail, true);
  assert.equal(s.sections.camera, true);
  const again = layoutReducer(s, { type: "openSection", section: "camera" });
  assert.equal(again.sections.camera, true);
});

test("layout carries a zoom (fit by default), setZoom changes it, loadLayout rejects junk zooms", () => {
  assert.equal(DEFAULT_LAYOUT.zoom, "fit");
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setZoom", zoom: 2 }).zoom, 2);
  const st = new Map<string, string>();
  const storage = { getItem: (k: string) => st.get(k) ?? null, setItem: (k: string, v: string) => { st.set(k, v); } } as unknown as Storage;
  st.set("fri.layout.v1", JSON.stringify({ zoom: 7 }));
  assert.equal(loadLayout(storage).zoom, "fit");
  st.set("fri.layout.v1", JSON.stringify({ zoom: 1 }));
  assert.equal(loadLayout(storage).zoom, 1);
});

test("visibleMode: rail by default; side / overlay set by action; legacy visibleSide migrates; junk rejected", () => {
  assert.equal(DEFAULT_LAYOUT.visibleMode, "rail");
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setVisibleMode", mode: "overlay" }).visibleMode, "overlay");
  const st = new Map<string, string>();
  const storage = { getItem: (k: string) => st.get(k) ?? null, setItem: (k: string, v: string) => { st.set(k, v); } } as unknown as Storage;
  st.set("fri.layout.v1", JSON.stringify({ visibleMode: "sideways" }));
  assert.equal(loadLayout(storage).visibleMode, "rail");
  st.set("fri.layout.v1", JSON.stringify({ visibleSide: true }));
  assert.equal(loadLayout(storage).visibleMode, "side");
  st.set("fri.layout.v1", JSON.stringify({ visibleMode: "overlay" }));
  assert.equal(loadLayout(storage).visibleMode, "overlay");
});

test("overlay registration: defaults, partial updates are clamped, persisted values validated", () => {
  assert.deepEqual(DEFAULT_LAYOUT.overlay, { opacity: 0.5, scale: 1, dx: 0, dy: 0 });
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "setOverlay", patch: { opacity: 1.7, scale: 0.1, dx: -80, dy: 12 } });
  assert.deepEqual(s1.overlay, { opacity: 1, scale: 0.5, dx: -50, dy: 12 });
  const st = new Map<string, string>();
  const storage = { getItem: (k: string) => st.get(k) ?? null, setItem: (k: string, v: string) => { st.set(k, v); } } as unknown as Storage;
  st.set("fri.layout.v1", JSON.stringify({ overlay: { opacity: "x", scale: 1.25, dx: 3 } }));
  assert.deepEqual(loadLayout(storage).overlay, { opacity: 0.5, scale: 1.25, dx: 3, dy: 0 });
});

test("hot/cold markers default on, toggle, and survive a reload", () => {
  const s0 = layoutReducer(DEFAULT_LAYOUT, { type: "setZoom", zoom: 1 });
  assert.equal(s0.extremes, true);
  const s1 = layoutReducer(s0, { type: "setExtremes", on: false });
  assert.equal(s1.extremes, false);
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s1);
  assert.equal(loadLayout(storage).extremes, false);
});

test("isotherm settings live in the layout and persist", () => {
  assert.equal(DEFAULT_LAYOUT.isotherm.mode, "off");
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "setIsotherm", isotherm: { mode: "above", lo: 50, hi: 60, color: "#00ff88" } });
  assert.equal(s1.isotherm.mode, "above");
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s1);
  assert.deepEqual(loadLayout(storage).isotherm, s1.isotherm);
});

test("delta pair (A − B) lives in the layout, persists, and clears with null", () => {
  assert.equal(DEFAULT_LAYOUT.delta, null);
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "setDelta", delta: { a: 2, b: 5 } });
  assert.deepEqual(s1.delta, { a: 2, b: 5 });
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s1);
  assert.deepEqual(loadLayout(storage).delta, { a: 2, b: 5 });
  assert.equal(layoutReducer(s1, { type: "setDelta", delta: null }).delta, null);
});

test("rail sections can pop out into floating windows, move/resize, and dock back; persisted", () => {
  assert.deepEqual(DEFAULT_LAYOUT.floating, {});
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "popOut", section: "measurements" });
  assert.ok(s1.floating.measurements && s1.floating.measurements.w >= 300);
  const s2 = layoutReducer(s1, { type: "moveFloat", section: "measurements", rect: { x: 40, y: 50, w: 500, h: 400 } });
  assert.deepEqual(s2.floating.measurements, { x: 40, y: 50, w: 500, h: 400 });
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s2);
  assert.deepEqual(loadLayout(storage).floating.measurements, { x: 40, y: 50, w: 500, h: 400 });
  const s3 = layoutReducer(s2, { type: "dockBack", section: "measurements" });
  assert.equal(s3.floating.measurements, undefined);
});

test("flip and temporal hold live in the layout with safe defaults", () => {
  assert.equal(DEFAULT_LAYOUT.flipH, false);
  assert.equal(DEFAULT_LAYOUT.hold, "off");
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "setFlip", h: true, v: false });
  assert.equal(s1.flipH, true);
  const s2 = layoutReducer(s1, { type: "setHold", hold: "max" });
  assert.equal(s2.hold, "max");
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s2);
  assert.equal(loadLayout(storage).flipH, true);
  assert.equal(loadLayout(storage).hold, "off", "hold is a session choice: never restored");
});

test("AGC setting (linear / plateau + strength) lives in the layout and persists", () => {
  assert.deepEqual(DEFAULT_LAYOUT.agc, { mode: "linear", plateau: 0.5 });
  const s1 = layoutReducer(DEFAULT_LAYOUT, { type: "setAgc", agc: { mode: "plateau", plateau: 0.8 } });
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } } as unknown as Storage;
  saveLayout(storage, s1);
  assert.deepEqual(loadLayout(storage).agc, { mode: "plateau", plateau: 0.8 });
  assert.equal(layoutReducer(DEFAULT_LAYOUT, { type: "setAgc", agc: { mode: "plateau", plateau: 7 } }).agc.plateau, 1, "clamped");
});
