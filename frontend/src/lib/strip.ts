/** Pure state logic for the tool-strip action shortcuts (StripActions). */

/**
 * One press of the visible-camera overlay button, as a three-state cycle:
 *   off/closed → on/open (show overlay + opacity slider)
 *   on/open    → on/closed (dismiss the slider, overlay STAYS on)
 *   on/closed  → off/closed (turn the overlay off)
 *
 * `open` is the next slider-flyout state (local to the button); `toggleOverlay` is true only on the
 * transitions that flip the parent's overlay on/off. Decoupling the flyout from the overlay is what
 * lets the overlay persist when the user just wants to close the slider.
 */
export function visibleButtonPress(on: boolean, open: boolean): { open: boolean; toggleOverlay: boolean } {
  if (!on) return { open: true, toggleOverlay: true };   // off → on + open slider
  if (open) return { open: false, toggleOverlay: false }; // dismiss slider, keep overlay on
  return { open: false, toggleOverlay: true };            // on + closed → off
}
