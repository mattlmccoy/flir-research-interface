// UI helpers for the visible-video adjustment: the SVG filter that shows it, the block stamped into
// a new recording, and the short notes beside the sliders. The model itself is visibleAdjust.ts.
import { ADJUST_LIMITS, adjustEqual, adjustLinear, clampAdjust, type VisibleAdjust } from "./visibleAdjust.ts";

/** Where a run's shown adjustment comes from (`GET /api/experiments/{name}` → `visible_adjust.source`). */
export type AdjustSource = "sidecar" | "recorded" | "neutral";
/** What the visible video route served (`X-Visible-Range` header). */
export type VisibleRange = "full" | "raw-untagged";

/** The `visible_adjust` block a recording start/arm request carries (stored in `metadata.json`). */
export interface RecordStamp extends VisibleAdjust {
  /** The last-applied preset's name, only when the values still equal that preset's. */
  preset: string | null;
  /** The last-applied preset's name when the values were changed after applying it. */
  based_on: string | null;
}

/** The `slope` / `intercept` attributes of the feFuncR/G/B elements, exact (shortest round-trip). */
export function filterTableValues(a: Readonly<VisibleAdjust>): { slope: string; intercept: string } {
  const { slope, intercept } = adjustLinear(a);
  return { slope: String(slope), intercept: String(intercept) };
}

/** A DOM id for the SVG filter of this map. It changes with the values, so a slider move always
 *  points the element at a new filter (browsers do not always repaint when a filter is edited in place). */
export function svgFilterId(a: Readonly<VisibleAdjust>): string {
  const { slope, intercept } = filterTableValues(a);
  const safe = (s: string) => s.replace(/-/g, "m").replace(/\./g, "p").replace(/\+/g, "");
  return `fri-vadj-${safe(slope)}_${safe(intercept)}`;
}

/** The stamp for a new recording from the live values and the last-applied preset (if any). */
export function recordStamp(
  current: Readonly<VisibleAdjust>,
  lastApplied: { name: string; visible_adjust: VisibleAdjust } | null,
): RecordStamp {
  const values = clampAdjust(current);
  if (!lastApplied) return { ...values, preset: null, based_on: null };
  const same = adjustEqual(values, clampAdjust(lastApplied.visible_adjust));
  return { ...values, preset: same ? lastApplied.name : null, based_on: same ? null : lastApplied.name };
}

/** The warning shown when the visible video plays without the full-range correction; null otherwise. */
export function rangeNote(visibleRange: string | null | undefined): string | null {
  return visibleRange === "raw-untagged" ? "visible video shown without range correction" : null;
}

/** The `X-Visible-Range` header value, or null when absent or not one the operator sends. */
export function parseRangeHeader(h: string | null): VisibleRange | null {
  const v = h?.trim();
  return v === "full" || v === "raw-untagged" ? v : null;
}

/** The numbers of a recorded `visible_adjust` stamp, or null when there is none or it is invalid
 *  (a control missing, not a number, or out of range), like the backend's `recorded_adjust`. */
export function recordedAdjust(block: unknown): VisibleAdjust | null {
  if (!block || typeof block !== "object" || Array.isArray(block)) return null;
  const o = block as Record<string, unknown>;
  const out: Partial<VisibleAdjust> = {};
  for (const k of Object.keys(ADJUST_LIMITS) as (keyof VisibleAdjust)[]) {
    const v = o[k];
    const [lo, hi] = ADJUST_LIMITS[k];
    if (typeof v !== "number" || !Number.isFinite(v) || v < lo || v > hi) return null;
    out[k] = v;
  }
  return out as VisibleAdjust;
}

/** Small text beside the playback sliders: where the shown adjustment comes from. */
export function sourceNote(source: AdjustSource): string {
  return source === "sidecar" ? "saved for this run" : source === "recorded" ? "as recorded" : "no adjustment";
}
