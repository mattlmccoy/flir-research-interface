import { test } from "node:test";
import assert from "node:assert/strict";
import { ZOOMS, displaySize, nextZoom, zoomLabel } from "./zoom.ts";

test("displaySize 'fit' contains the image in the box keeping 4:3 and scales UP as well as down", () => {
  assert.deepEqual(displaySize(640, 480, 1600, 900, "fit"), { width: 1200, height: 900 });
  assert.deepEqual(displaySize(640, 480, 1000, 1000, "fit"), { width: 1000, height: 750 });
  assert.deepEqual(displaySize(640, 480, 320, 300, "fit"), { width: 320, height: 240 });
});

test("displaySize numeric zoom is exact pixels regardless of the box", () => {
  assert.deepEqual(displaySize(640, 480, 300, 300, 1), { width: 640, height: 480 });
  assert.deepEqual(displaySize(640, 480, 300, 300, 2), { width: 1280, height: 960 });
});

test("nextZoom cycles fit → 1 → 2 → fit and labels read well", () => {
  assert.equal(nextZoom("fit"), 1);
  assert.equal(nextZoom(1), 2);
  assert.equal(nextZoom(2), "fit");
  assert.equal(zoomLabel("fit"), "fit");
  assert.equal(zoomLabel(1), "1:1");
  assert.equal(zoomLabel(2), "2×");
  assert.deepEqual(ZOOMS, ["fit", 1, 2]);
});
