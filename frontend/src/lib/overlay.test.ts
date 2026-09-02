import { test } from "node:test";
import assert from "node:assert/strict";
import { clientToImage, hitTest, traceColor } from "./overlay.ts";
import type { Roi } from "./roi.ts";

const RECT = { left: 100, top: 50, width: 320, height: 240 }; // canvas drawn at half size of 640x480

test("clientToImage maps client coords onto image pixels and clamps to the edge", () => {
  assert.deepEqual(clientToImage(RECT, 100, 50, 640, 480), { x: 0, y: 0 });
  assert.deepEqual(clientToImage(RECT, 260, 170, 640, 480), { x: 320, y: 240 });
  assert.deepEqual(clientToImage(RECT, 419.9, 289.9, 640, 480), { x: 639, y: 479 });
  assert.deepEqual(clientToImage(RECT, 9999, -5, 640, 480), { x: 639, y: 0 });
});

test("hitTest prefers spots (within tolerance) then rects, topmost last-added first", () => {
  const rois: Roi[] = [
    { id: 1, kind: "rect", x0: 10, y0: 10, x1: 100, y1: 100 },
    { id: 2, kind: "rect", x0: 50, y0: 50, x1: 200, y1: 200 },
    { id: 3, kind: "spot", x: 60, y: 60 },
  ];
  assert.equal(hitTest(rois, 62, 58, 6), 3);
  assert.equal(hitTest(rois, 70, 70, 6), 2);
  assert.equal(hitTest(rois, 20, 20, 6), 1);
  assert.equal(hitTest(rois, 300, 300, 6), null);
});

test("traceColor cycles through the token list deterministically", () => {
  assert.equal(traceColor(0), "var(--live)");
  assert.equal(traceColor(1), "var(--accent)");
  assert.equal(traceColor(6), traceColor(0));
});
