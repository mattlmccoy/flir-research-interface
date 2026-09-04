import { test } from "node:test";
import assert from "node:assert/strict";
import { layoutLabels, type LabelBox } from "./labels.ts";

const BOX = { width: 400, height: 300 };
const mk = (id: number, ax: number, ay: number, w = 100, h = 16): LabelBox => ({ id, ax, ay, w, h });

test("labels far apart keep their anchor position", () => {
  const out = layoutLabels([mk(1, 10, 10), mk(2, 10, 200)], BOX);
  const a = out.find((p) => p.id === 1)!, b = out.find((p) => p.id === 2)!;
  assert.equal(a.y, 10); assert.equal(b.y, 200);
  assert.equal(a.displaced, false); assert.equal(b.displaced, false);
});

test("labels overlapping in both x and y are pushed apart vertically", () => {
  const out = layoutLabels([mk(1, 10, 50), mk(2, 20, 52)], BOX); // near-identical anchors
  const a = out.find((p) => p.id === 1)!, b = out.find((p) => p.id === 2)!;
  // they must not overlap: |ay difference| >= height
  assert.ok(Math.abs(a.y - b.y) >= 16, `expected >=16 apart, got ${Math.abs(a.y - b.y)}`);
  assert.ok(a.displaced || b.displaced, "one was moved");
});

test("labels overlapping in y but not in x are independent", () => {
  const out = layoutLabels([mk(1, 0, 50, 80), mk(2, 300, 52, 80)], BOX); // different columns
  assert.equal(out.find((p) => p.id === 1)!.y, 50);
  assert.equal(out.find((p) => p.id === 2)!.y, 52);
});

test("positions are clamped inside the box", () => {
  const out = layoutLabels([mk(1, 380, 295, 100, 16)], BOX);
  const p = out[0];
  assert.ok(p.x >= 0 && p.x + 100 <= BOX.width, `x in box: ${p.x}`);
  assert.ok(p.y >= 0 && p.y + 16 <= BOX.height, `y in box: ${p.y}`);
});

test("a stack of coincident labels ends up non-overlapping", () => {
  const items = [1, 2, 3, 4].map((i) => mk(i, 50, 50));
  const out = layoutLabels(items, BOX);
  const ys = out.map((p) => p.y).sort((a, b) => a - b);
  for (let i = 1; i < ys.length; i++) assert.ok(ys[i] - ys[i - 1] >= 16, `row ${i} clears previous`);
});

test("priority items (listed first) stay at their anchor; others avoid them", () => {
  // id 1 is the selected/priority label at the front; id 2 must move off it
  const out = layoutLabels([mk(1, 50, 50), mk(2, 50, 50)], BOX);
  assert.equal(out.find((p) => p.id === 1)!.y, 50, "first-listed keeps its anchor");
  assert.notEqual(out.find((p) => p.id === 2)!.y, 50, "second moves");
});
