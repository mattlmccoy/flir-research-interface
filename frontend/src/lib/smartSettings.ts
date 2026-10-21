// Smart ROI settings input parsing (pure, so the rail editor stays a thin view).
import { MAX_RING_PX } from "./roi.ts";

export type RingParse = { ok: true; rings: number[] } | { ok: false; error: string };

/** Ring offsets typed as a comma list of px ("5, 10, 25"), checked the way the operator's
 *  parse_smart_roi checks them: whole pixels, positive, strictly increasing, at most MAX_RING_PX,
 *  at least one. */
export function parseRingOffsets(text: string): RingParse {
  const parts = text.split(",").map((p) => p.trim());
  if (parts.length === 1 && parts[0] === "") return { ok: false, error: "enter at least one ring offset in px" };
  const rings: number[] = [];
  for (const p of parts) {
    if (!/^\d+$/.test(p)) return { ok: false, error: `"${p}" is not a whole number of px` };
    const v = Number(p);
    if (v < 1) return { ok: false, error: "ring offsets must be at least 1 px" };
    if (v > MAX_RING_PX) return { ok: false, error: `ring offsets must be at most ${MAX_RING_PX} px` };
    if (rings.length && v <= rings[rings.length - 1]) return { ok: false, error: "ring offsets must be increasing" };
    rings.push(v);
  }
  return { ok: true, rings };
}
