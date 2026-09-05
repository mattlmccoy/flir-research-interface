/**
 * Flat line-icons for the tool-strip *action* shortcuts. Drawn as SVG (not unicode glyphs) so they
 * read as commands and never resemble the geometric ROI drawing tools (circle/rect/ellipse/…).
 * All use `currentColor`, so they follow the button's normal/active colour like the glyph tools.
 */
import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  width: 16, height: 16, viewBox: "0 0 16 16", fill: "none",
  stroke: "currentColor", strokeWidth: 1.3, strokeLinecap: "round", strokeLinejoin: "round",
  "aria-hidden": true, focusable: false,
};

/** Media export — a film frame with a play triangle (make a clip / GIF). */
export function IconClip() {
  return (
    <svg {...base}>
      <rect x="1.8" y="3.5" width="12.4" height="9" rx="1.6" />
      <path d="M6.4 6 L10 8 L6.4 10 Z" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Save image — a picture (frame + sun + mountains) with a down arrow, i.e. save this frame. */
export function IconSaveImage() {
  return (
    <svg {...base}>
      <path d="M12.5 2.5 h-9 A1.5 1.5 0 0 0 2 4 v8 A1.5 1.5 0 0 0 3.5 13.5 h6" />
      <circle cx="5.4" cy="6" r="1.05" />
      <path d="M2.4 11.5 L6 8 L8.2 10.2" />
      <path d="M12.5 8 V13 M10.7 11.2 L12.5 13 L14.3 11.2" />
    </svg>
  );
}

/** ROI visibility — an open eye (shown) or a slashed eye (hidden). */
export function IconEye({ off = false }: { off?: boolean }) {
  return (
    <svg {...base}>
      <path d="M1.5 8 C3.6 4.6 12.4 4.6 14.5 8 C12.4 11.4 3.6 11.4 1.5 8 Z" />
      <circle cx="8" cy="8" r="1.9" />
      {off && <path d="M2.5 2.5 L13.5 13.5" />}
    </svg>
  );
}

/** Visible-camera overlay — two offset layers (the visible image laid over the IR image). */
export function IconLayers() {
  return (
    <svg {...base}>
      <rect x="2.2" y="2.2" width="8" height="8" rx="1.4" />
      <path d="M5.8 13.8 h6 A1.6 1.6 0 0 0 13.4 12.2 v-6" />
    </svg>
  );
}

/** Regenerate — a circular refresh arrow. */
export function IconRefresh() {
  return (
    <svg {...base}>
      <path d="M12.6 6.4 A5 5 0 1 0 13 9.4" />
      <path d="M13.2 2.8 V6.6 H9.4" />
    </svg>
  );
}
