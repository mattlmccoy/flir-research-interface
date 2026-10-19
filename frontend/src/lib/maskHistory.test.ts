import { test } from "node:test";
import assert from "node:assert/strict";
import { EMPTY_MASKS, type MaskState } from "./mask.ts";
import { initMaskHistory, maskHistoryReducer, type MaskHistory, type MaskHistoryAction } from "./maskHistory.ts";

const run = (h: MaskHistory, ...as: MaskHistoryAction[]) => as.reduce(maskHistoryReducer, h);
const ids = (s: MaskState) => s.shapes.map((m) => m.id);
const box = { kind: "rect" as const, x0: 10, y0: 10, x1: 30, y1: 30 };

test("undo removes the region just drawn; redo puts it back", () => {
  let h = run(initMaskHistory(EMPTY_MASKS), { type: "add", shape: box });
  assert.deepEqual(ids(h.present), [1]);
  h = run(h, { type: "undo" });
  assert.deepEqual(ids(h.present), []);
  h = run(h, { type: "redo" });
  assert.deepEqual(ids(h.present), [1]);
});

test("a drag is one undo step", () => {
  let h = run(initMaskHistory(EMPTY_MASKS), { type: "add", shape: box });
  h = run(h, ...[1, 2, 3].map(() => ({ type: "edit", action: { type: "move", id: 1, dx: 1, dy: 0 } }) as MaskHistoryAction),
    { type: "edit", action: { type: "commit" } });
  assert.equal((h.present.shapes[0] as { x0: number }).x0, 13);
  h = run(h, { type: "undo" });
  assert.equal((h.present.shapes[0] as { x0: number }).x0, 10);
});

test("undo brings back a deleted region", () => {
  let h = run(initMaskHistory(EMPTY_MASKS), { type: "add", shape: box },
    { type: "edit", action: { type: "commit" } }, { type: "edit", action: { type: "remove", id: 1 } }, { type: "edit", action: { type: "commit" } });
  assert.deepEqual(ids(h.present), []);
  h = run(h, { type: "undo" });
  assert.deepEqual(ids(h.present), [1]);
});

test("selection, on/off and draw-mode changes are not undo steps", () => {
  let h = run(initMaskHistory(EMPTY_MASKS), { type: "add", shape: box },
    { type: "edit", action: { type: "select", id: 1 } }, { type: "setEnabled", enabled: false }, { type: "setDrawMode", mode: "exclude" });
  assert.equal(h.past.length, 1);
  h = run(h, { type: "undo" });
  assert.deepEqual(ids(h.present), []);
});

test("loading another scope's mask starts a fresh history", () => {
  let h = run(initMaskHistory(EMPTY_MASKS), { type: "add", shape: box });
  h = run(h, { type: "load", shapes: [] });
  assert.equal(h.past.length, 0);
  assert.equal(run(h, { type: "undo" }), h);
});
