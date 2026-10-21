// Recorded-run smart ROI outlines: the stored per-frame overlays (GET …/smart-roi/{id}/overlay),
// fetched a block of frames at a time and cached (useSmartPlaybackOverlays.ts); pure helpers here.
import type { SmartOverlay } from "./smartLabels.ts";

/** Key `${roiId}:${blockStart}` → that block's overlays, or "missing" (no stored series / failed). */
export type OverlayCache = Map<string, SmartOverlay[] | "missing">;

export const OVERLAY_BLOCK = 120;

export function overlayBlock(index: number, size: number): number {
  return Math.floor(index / size) * size;
}

/** The overlay of each ROI at frame `index` that is already cached (absent ones are skipped). */
export function pickOverlays(cache: OverlayCache, ids: number[], index: number, size: number): SmartOverlay[] {
  const start = overlayBlock(index, size);
  const out: SmartOverlay[] = [];
  for (const id of ids) {
    const block = cache.get(`${id}:${start}`);
    const o = Array.isArray(block) ? block[index - start] : undefined;
    if (o) out.push(o);
  }
  return out;
}
