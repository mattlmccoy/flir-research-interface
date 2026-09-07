import { test } from "node:test";
import assert from "node:assert/strict";
import { visibleButtonPress } from "./strip.ts";

// The visible-camera overlay button cycles through three states so that dismissing the opacity
// slider does NOT switch the overlay off (the reported bug). `toggleOverlay` tells the caller
// whether the parent's on/off state must flip; `open` is the local slider-flyout state.

test("pressing the button while the overlay is off turns it on and opens the slider", () => {
  assert.deepEqual(visibleButtonPress(false, false), { open: true, toggleOverlay: true });
});

test("pressing while the overlay is on with the slider open dismisses the slider but keeps the overlay on", () => {
  // this is the fix: the overlay persists (toggleOverlay false) — only the flyout closes
  assert.deepEqual(visibleButtonPress(true, true), { open: false, toggleOverlay: false });
});

test("pressing while the overlay is on with the slider already closed turns the overlay off", () => {
  assert.deepEqual(visibleButtonPress(true, false), { open: false, toggleOverlay: true });
});
