import { test } from "node:test";
import assert from "node:assert/strict";
import { EMPTY_ROIS, type Roi } from "./roi.ts";
import { HISTORY_LIMIT, initHistory, roiHistoryReducer as r, type RoiHistory, type RoiHistoryAction } from "./roiHistory.ts";

const run = (h: RoiHistory, ...as: RoiHistoryAction[]) => as.reduce(r, h);
const spot = (x: number): RoiHistoryAction => ({ type: "add", roi: { kind: "spot", x, y: 1 } });
const xOf = (h: RoiHistory, id: number) => (h.present.rois.find((q) => q.id === id) as Extract<Roi, { kind: "spot" }>).x;

test("undo and redo an add", () => {
  const h = run(initHistory(EMPTY_ROIS), spot(5));
  const u = r(h, { type: "undo" });
  assert.equal(u.present.rois.length, 0);
  const re = r(u, { type: "redo" });
  assert.deepEqual(re.present.rois, h.present.rois);
});

test("a drag is one undo step; the next drag is another", () => {
  let h = run(initHistory(EMPTY_ROIS), spot(5));
  h = run(h, { type: "move", id: 1, dx: 1, dy: 0 }, { type: "move", id: 1, dx: 1, dy: 0 }, { type: "move", id: 1, dx: 1, dy: 0 }, { type: "commit" });
  h = run(h, { type: "move", id: 1, dx: 10, dy: 0 }, { type: "commit" });
  assert.equal(xOf(h, 1), 18);
  h = r(h, { type: "undo" });
  assert.equal(xOf(h, 1), 8);
  h = r(h, { type: "undo" });
  assert.equal(xOf(h, 1), 5);
  h = run(h, { type: "redo" }, { type: "redo" });
  assert.equal(xOf(h, 1), 18);
});

test("selection changes are not undo steps", () => {
  let h = run(initHistory(EMPTY_ROIS), spot(5), spot(6), { type: "select", id: 1 }, { type: "select", id: null });
  assert.equal(h.past.length, 2);
  h = r(h, { type: "undo" });
  assert.equal(h.present.rois.length, 1);
});

test("a new edit clears redo", () => {
  let h = run(initHistory(EMPTY_ROIS), spot(5), { type: "undo" });
  assert.equal(h.future.length, 1);
  h = r(h, spot(7));
  assert.equal(h.future.length, 0);
  assert.equal(r(h, { type: "redo" }), h);
});

test("ids are not reused after undoing an add", () => {
  const h = run(initHistory(EMPTY_ROIS), spot(5), { type: "undo" }, spot(6));
  assert.equal(h.present.rois[0].id, 2);
});

test("deleting a multi-selection undoes in one step", () => {
  let h = run(initHistory(EMPTY_ROIS), spot(1), spot(2), spot(3));
  h = run(h, { type: "commit" }, { type: "remove", id: 1 }, { type: "remove", id: 2 }, { type: "commit" });
  assert.equal(h.present.rois.length, 1);
  h = r(h, { type: "undo" });
  assert.equal(h.present.rois.length, 3);
});

test("load replaces the ROIs and forgets history", () => {
  let h = run(initHistory(EMPTY_ROIS), spot(1), spot(2));
  h = r(h, { type: "load", rois: [{ id: 9, kind: "spot", x: 0, y: 0 }] });
  assert.equal(h.past.length, 0);
  assert.equal(r(h, { type: "undo" }), h);
  assert.equal(h.present.nextId, 10);
});

test("history is capped", () => {
  let h = initHistory(EMPTY_ROIS);
  for (let i = 0; i < HISTORY_LIMIT + 20; i++) h = r(h, spot(i));
  assert.equal(h.past.length, HISTORY_LIMIT);
});

test("clearing no ROIs adds no step", () => {
  const h = r(initHistory(EMPTY_ROIS), { type: "clear" });
  assert.equal(h.past.length, 0);
});
