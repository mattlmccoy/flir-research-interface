/** Image zoom for the Studio center: "fit" (contain, scales up too), or an exact pixel factor. */

export type Zoom = "fit" | 1 | 2;
export const ZOOMS: readonly Zoom[] = ["fit", 1, 2];

/** CSS size for a w×h image inside a boxW×boxH cell at the given zoom (aspect preserved). */
export function displaySize(w: number, h: number, boxW: number, boxH: number, zoom: Zoom): { width: number; height: number } {
  if (zoom !== "fit") return { width: w * zoom, height: h * zoom };
  if (w <= 0 || h <= 0 || boxW <= 0 || boxH <= 0) return { width: w, height: h };
  const s = Math.min(boxW / w, boxH / h);
  return { width: Math.floor(w * s), height: Math.floor(h * s) };
}

export function nextZoom(z: Zoom): Zoom {
  return ZOOMS[(ZOOMS.indexOf(z) + 1) % ZOOMS.length];
}

export function zoomLabel(z: Zoom): string {
  return z === "fit" ? "fit" : z === 1 ? "1:1" : `${z}×`;
}

export function isZoom(v: unknown): v is Zoom {
  return v === "fit" || v === 1 || v === 2;
}
