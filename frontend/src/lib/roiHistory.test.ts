import { test } from "node:test";
import assert from "node:assert/strict";
import { EMPTY_ROIS } from "./roi.ts";
import { initRoiHistory, roiHistoryReducer, undoKeyFor, type RoiHistory } from "./roiHistory.ts";

const start = (): RoiHistory => {
  let h = initRoiHistory(EMPTY_ROIS);
  h = roiHistoryReducer(h, { type: "add", roi: { kind: "spot", x: 10, y: 10 } });
  h = roiHistoryReducer(h, { type: "commit" });
  return h;
};
const spotX = (h: RoiHistory) => { const r = h.present.rois[0]; return r.kind === "spot" ? r.x : NaN; };

test("undo reverts a whole drag (many move actions) in one step, redo reapplies it", () => {
  let h = start();
  for (let i = 0; i < 5; i++) h = roiHistoryReducer(h, { type: "move", id: 1, dx: 2, dy: 0 });
  h = roiHistoryReducer(h, { type: "commit" });
  assert.equal(spotX(h), 20);
  h = roiHistoryReducer(h, { type: "undo" });
  assert.equal(spotX(h), 10);
  h = roiHistoryReducer(h, { type: "redo" });
  assert.equal(spotX(h), 20);
});

test("two separate drags of the same ROI are two undo steps", () => {
  let h = start();
  h = roiHistoryReducer(h, { type: "move", id: 1, dx: 5, dy: 0 });
  h = roiHistoryReducer(h, { type: "commit" });
  h = roiHistoryReducer(h, { type: "move", id: 1, dx: 5, dy: 0 });
  h = roiHistoryReducer(h, { type: "commit" });
  h = roiHistoryReducer(h, { type: "undo" });
  assert.equal(spotX(h), 15);
});

test("undo also reverts adding an ROI; selection-only actions are not undo steps", () => {
  let h = start();
  h = roiHistoryReducer(h, { type: "select", id: null });
  h = roiHistoryReducer(h, { type: "undo" });
  assert.equal(h.present.rois.length, 0);
  assert.equal(h.present.selected, null);
});

test("a new edit after undo clears the redo stack", () => {
  let h = start();
  h = roiHistoryReducer(h, { type: "move", id: 1, dx: 5, dy: 0 });
  h = roiHistoryReducer(h, { type: "commit" });
  h = roiHistoryReducer(h, { type: "undo" });
  h = roiHistoryReducer(h, { type: "move", id: 1, dx: 1, dy: 0 });
  const again = roiHistoryReducer(h, { type: "redo" });
  assert.equal(spotX(again), 11);
});

test("undo and redo with nothing to do return the same state", () => {
  const h = initRoiHistory(EMPTY_ROIS);
  assert.equal(roiHistoryReducer(h, { type: "undo" }), h);
  assert.equal(roiHistoryReducer(h, { type: "redo" }), h);
});

test("undo keeps ids unique: nextId never goes back", () => {
  let h = start();
  h = roiHistoryReducer(h, { type: "undo" });
  h = roiHistoryReducer(h, { type: "add", roi: { kind: "spot", x: 1, y: 1 } });
  assert.equal(h.present.rois[0].id, 2);
});

test("undo drops selection of ROIs that no longer exist", () => {
  let h = start();
  assert.equal(h.present.selected, 1);
  h = roiHistoryReducer(h, { type: "undo" });
  assert.equal(h.present.selected, null);
  assert.deepEqual(h.present.selectedIds, []);
});

test("replace (switching run scope) clears history so undo cannot restore another run's ROIs", () => {
  let h = start();
  h = roiHistoryReducer(h, { type: "replace", rois: [] });
  assert.equal(roiHistoryReducer(h, { type: "undo" }), h);
});

test("undoKeyFor maps cmd/ctrl+Z to undo and cmd/ctrl+Y or shift+cmd/ctrl+Z to redo", () => {
  const k = (key: string, o: { meta?: boolean; ctrl?: boolean; shift?: boolean; alt?: boolean } = {}) =>
    undoKeyFor({ key, metaKey: !!o.meta, ctrlKey: !!o.ctrl, shiftKey: !!o.shift, altKey: !!o.alt });
  assert.equal(k("z", { meta: true }), "undo");
  assert.equal(k("z", { ctrl: true }), "undo");
  assert.equal(k("Z", { meta: true, shift: true }), "redo");
  assert.equal(k("y", { ctrl: true }), "redo");
  assert.equal(k("y", { meta: true }), "redo");
  assert.equal(k("z"), null);
  assert.equal(k("z", { meta: true, alt: true }), null);
  assert.equal(k("x", { meta: true }), null);
});
