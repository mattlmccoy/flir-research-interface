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

/** The note when the served video is known to lack the full-range correction. */
export const RAW_RANGE_NOTE = "visible video shown without range correction";
/** The note when nothing confirms the correction (no header, the probe failed, or no prediction). */
export const UNCONFIRMED_RANGE_NOTE = "range correction not confirmed";

/** The note for the shown visible video: none when it is full range, else what is wrong or unknown.
 *  Unknown (null / undefined) never reads as healthy. */
export function rangeNote(visibleRange: VisibleRange | null | undefined): string | null {
  if (visibleRange === "full") return null;
  return visibleRange === "raw-untagged" ? RAW_RANGE_NOTE : UNCONFIRMED_RANGE_NOTE;
}

/** The range to show: the header probe's answer once it is in (`probe`, null range = failed or no
 *  header), and the info's prediction (`fallback`) only while the probe is pending (`undefined`). */
export function effectiveRange(
  probe: { range: VisibleRange | null } | undefined,
  fallback: VisibleRange | null | undefined,
): VisibleRange | null {
  return probe ? probe.range : (fallback ?? null);
}

/** The X-Visible-Range of `url` via `read`, sharing one read per URL in `cache`; a read that fails
 *  or carries no valid header is dropped from the cache, so the next mount or run asks again. */
export function cachedRangeProbe(
  cache: Map<string, Promise<VisibleRange | null>>,
  url: string,
  read: (url: string) => Promise<string | null>,
): Promise<VisibleRange | null> {
  const hit = cache.get(url);
  if (hit) return hit;
  const p = read(url).then(parseRangeHeader, () => null).then((range) => {
    if (range === null && cache.get(url) === p) cache.delete(url);
    return range;
  });
  cache.set(url, p);
  return p;
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
