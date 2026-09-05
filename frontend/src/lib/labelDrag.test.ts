import { test } from "node:test";
import assert from "node:assert/strict";
import { hitChip, loadOffsets, saveOffsets, offsetsKey, type ChipRect } from "./labelDrag.ts";

const rects: ChipRect[] = [
  { id: 1, x: 0, y: 0, w: 100, h: 20 },
  { id: 2, x: 50, y: 10, w: 100, h: 20 }, // overlaps ROI 1 in (50..100, 10..20)
];

test("hitChip: returns the topmost chip under the point", () => {
  assert.equal(hitChip(rects, 10, 5), 1); // only inside ROI 1
  assert.equal(hitChip(rects, 120, 15), 2); // only inside ROI 2
  assert.equal(hitChip(rects, 60, 15), 2); // overlap → topmost (last drawn) wins
  assert.equal(hitChip(rects, 200, 200), null); // outside all
});

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
    removeItem: (k) => void m.delete(k),
    clear: () => m.clear(),
    key: () => null,
    length: 0,
  } as Storage;
}

test("offsets round-trip through storage, scoped by key", () => {
  const s = memStorage();
  saveOffsets(s, "exp.run1", { 7: { dx: 12, dy: -8 } });
  assert.deepEqual(loadOffsets(s, "exp.run1"), { 7: { dx: 12, dy: -8 } });
  assert.deepEqual(loadOffsets(s, "live"), {}); // different scope is independent
  assert.notEqual(offsetsKey("live"), offsetsKey("exp.run1"));
});

test("saving an empty map clears the key (back to auto layout)", () => {
  const s = memStorage();
  saveOffsets(s, "live", { 3: { dx: 5, dy: 5 } });
  saveOffsets(s, "live", {});
  assert.equal(s.getItem(offsetsKey("live")), null);
  assert.deepEqual(loadOffsets(s, "live"), {});
});

test("loadOffsets ignores non-finite junk", () => {
  const s = memStorage();
  s.setItem(offsetsKey("live"), JSON.stringify({ 1: { dx: 3, dy: 4 }, 2: { dx: "x", dy: 1 } }));
  assert.deepEqual(loadOffsets(s, "live"), { 1: { dx: 3, dy: 4 } });
});
