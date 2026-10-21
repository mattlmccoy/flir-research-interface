import assert from "node:assert/strict";
import { test } from "node:test";
import { overlayBlock, pickOverlays, type OverlayCache } from "./smartPlayback.ts";
import type { SmartOverlay } from "./smartLabels.ts";

const ov = (id: number, state: SmartOverlay["state"]): SmartOverlay => ({ id, state, valid: state !== "searching", bbox: null, labels: null });

test("overlayBlock is the block start holding a frame index", () => {
  assert.equal(overlayBlock(0, 120), 0);
  assert.equal(overlayBlock(119, 120), 0);
  assert.equal(overlayBlock(120, 120), 120);
  assert.equal(overlayBlock(250, 120), 240);
});

test("pickOverlays takes each ROI's overlay for the index from its cached block", () => {
  const cache: OverlayCache = new Map<string, SmartOverlay[] | "missing">([
    ["1:120", [ov(1, "searching"), ov(1, "locked"), ov(1, "holding")]],
    ["2:120", "missing"],  // no stored series for ROI 2
  ]);
  assert.deepEqual(pickOverlays(cache, [1, 2], 121, 120), [ov(1, "locked")]);
  assert.deepEqual(pickOverlays(cache, [1], 125, 120), [], "past the end of the stored window");
  assert.deepEqual(pickOverlays(cache, [1], 5, 120), [], "block not loaded yet");
});
