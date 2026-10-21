// Per smart ROI display choices kept in the browser layout (lib/layout.ts, localStorage): whether
// its rail row is expanded, and which ring bands are hidden. Display only: the ROI spec (and so
// its signature, stale detection, tracking, stored series, CSV and TC-POWER feed) never changes.

/** `hiddenRings` holds ring outer offsets in px (the ROI's rings_px values). */
export interface SmartRowPrefs { expanded: boolean; hiddenRings: number[]; }
/** Keyed by ROI id (as a string, the JSON object key). */
export type SmartViewPrefs = Readonly<Record<string, SmartRowPrefs>>;

const DEFAULT: SmartRowPrefs = { expanded: false, hiddenRings: [] };

export function smartPrefs(v: SmartViewPrefs, id: number): SmartRowPrefs {
  return v[String(id)] ?? DEFAULT;
}

/** Validates the stored value: integer ROI ids, a boolean, integer ring offsets. */
export function parseSmartView(raw: unknown): SmartViewPrefs {
  const out: Record<string, SmartRowPrefs> = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!/^\d+$/.test(k) || !v || typeof v !== "object") continue;
    const o = v as Record<string, unknown>;
    const rings = Array.isArray(o.hiddenRings) ? o.hiddenRings.filter((x): x is number => Number.isInteger(x)) : [];
    out[k] = { expanded: o.expanded === true, hiddenRings: rings };
  }
  return out;
}

export function toggleSmartExpanded(v: SmartViewPrefs, id: number): SmartViewPrefs {
  const p = smartPrefs(v, id);
  return { ...v, [String(id)]: { ...p, expanded: !p.expanded } };
}

export function toggleSmartRing(v: SmartViewPrefs, id: number, outerPx: number): SmartViewPrefs {
  const p = smartPrefs(v, id);
  const hidden = p.hiddenRings.includes(outerPx) ? p.hiddenRings.filter((x) => x !== outerPx) : [...p.hiddenRings, outerPx];
  return { ...v, [String(id)]: { ...p, hiddenRings: hidden } };
}

/** Ring bands still shown (readout rows, plot traces). */
export function visibleRings<T extends { outer_px: number }>(rings: T[], hidden: readonly number[]): T[] {
  return hidden.length ? rings.filter((g) => !hidden.includes(g.outer_px)) : rings;
}

/** Outline ring loops still shown: loop q belongs to the ROI's ring `ringsPx[q]`; a loop with no
 *  matching offset (a stored outline computed with more rings) is always drawn. */
export function visibleOutlineRings<L>(rings: L[], ringsPx: readonly number[], hidden: readonly number[]): L[] {
  return hidden.length ? rings.filter((_, q) => !(q < ringsPx.length && hidden.includes(ringsPx[q]))) : rings;
}
