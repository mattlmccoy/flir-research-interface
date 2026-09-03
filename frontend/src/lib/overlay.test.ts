import { test } from "node:test";
import assert from "node:assert/strict";
import { COLOR_PRESETS, clientToImage, hitTest, roiColor, traceColor, vertexHit } from "./overlay.ts";
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

test("hitTest handles circles (inside), lines and polylines (within tolerance of a segment)", () => {
  const rois: Roi[] = [
    { id: 1, kind: "circle", cx: 50, cy: 50, r: 10 },
    { id: 2, kind: "line", x0: 100, y0: 100, x1: 200, y1: 100 },
    { id: 3, kind: "polygon", points: [[300, 300], [300, 400], [400, 400]] },
  ];
  assert.equal(hitTest(rois, 55, 52, 6), 1);
  assert.equal(hitTest(rois, 70, 50, 6), null);
  assert.equal(hitTest(rois, 150, 103, 6), 2);
  assert.equal(hitTest(rois, 150, 120, 6), null);
  assert.equal(hitTest(rois, 320, 380, 6), 3); // inside the triangle
  assert.equal(hitTest(rois, 380, 320, 6), null); // outside (other half of the square)
});


test("roiColor: explicit colour wins, otherwise the trace token by index; presets are 9 hex colours", () => {
  assert.equal(roiColor({ id: 1, kind: "spot", x: 0, y: 0, color: "#123456" }, 3), "#123456");
  assert.equal(roiColor({ id: 1, kind: "spot", x: 0, y: 0 }, 1), "var(--accent)");
  assert.equal(COLOR_PRESETS.length, 9);
  for (const c of COLOR_PRESETS) assert.match(c, /^#[0-9a-f]{6}$/);
});

test("vertexHit finds a polygon/polyline vertex or a line endpoint within tolerance", () => {
  const poly = { id: 1, kind: "polygon" as const, points: [[0, 0], [10, 0], [10, 10]] as [number, number][] };
  assert.deepEqual(vertexHit(poly, 10, 1, 2), { kind: "vertex", index: 1 });
  assert.equal(vertexHit(poly, 5, 5, 2), null);
  const line = { id: 2, kind: "line" as const, x0: 2, y0: 2, x1: 20, y1: 20 };
  assert.deepEqual(vertexHit(line, 21, 19, 2), { kind: "endpoint", end: 1 });
  assert.deepEqual(vertexHit(line, 2, 3, 2), { kind: "endpoint", end: 0 });
  assert.equal(vertexHit({ id: 3, kind: "spot", x: 1, y: 1 }, 1, 1, 2), null, "no vertices on a spot");
});
