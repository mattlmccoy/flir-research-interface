// Smart ROI readout text. The numbers always come from the operator (GET /api/live/roi-temps smart
// entries, backend analysis/live_temps.py _smart_entry); the browser never re-measures a smart ROI.

export type SmartState = "searching" | "locked" | "holding";
export interface SmartStats { mean_c: number | null; max_c: number | null; min_c: number | null; }
export interface SmartRing extends SmartStats { inner_px: number; outer_px: number; }
/** Per-frame dimensions in pixels, measured from the thermal edge (smart_roi.py _dims). */
export interface SmartDims {
  area_px: number; length_px: number; width_px: number; perimeter_px: number;
  centroid_x: number; centroid_y: number; sharpness_c_per_px: number | null;
  area_change_pct: number | null; length_change_pct: number | null; width_change_pct: number | null;
  units: "px";
}
export interface SmartReadoutEntry {
  state: SmartState; valid: boolean; over_range: boolean;
  sample: SmartStats; rings: SmartRing[]; dims: SmartDims | null;
}

const STATES: readonly SmartState[] = ["searching", "locked", "holding"];
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const stats = (o: Record<string, unknown>): SmartStats => ({ mean_c: num(o.mean_c), max_c: num(o.max_c), min_c: num(o.min_c) });

function asDims(v: unknown): SmartDims | null {
  if (!v || typeof v !== "object") return null;
  const d = v as Record<string, unknown>;
  const req = ["area_px", "length_px", "width_px", "perimeter_px", "centroid_x", "centroid_y"] as const;
  if (!req.every((k) => num(d[k]) !== null)) return null;
  return {
    area_px: d.area_px as number, length_px: d.length_px as number, width_px: d.width_px as number,
    perimeter_px: d.perimeter_px as number, centroid_x: d.centroid_x as number, centroid_y: d.centroid_y as number,
    sharpness_c_per_px: num(d.sharpness_c_per_px),
    area_change_pct: num(d.area_change_pct), length_change_pct: num(d.length_change_pct), width_change_pct: num(d.width_change_pct),
    units: "px",
  };
}

/** A smart entry of the live feed, or null when `raw` is not one. Valid only when the operator says
 *  so and every sample number is present (unknown never reads as healthy). */
export function smartEntryFromFeed(raw: unknown): SmartReadoutEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (r.kind !== "smart" || !STATES.includes(r.state as SmartState)) return null;
  const sample = stats(r);
  const rings = (Array.isArray(r.rings) ? r.rings : [])
    .filter((g): g is Record<string, unknown> => !!g && typeof g === "object" && num((g as Record<string, unknown>).inner_px) !== null && num((g as Record<string, unknown>).outer_px) !== null)
    .map((g) => ({ inner_px: g.inner_px as number, outer_px: g.outer_px as number, ...stats(g) }));
  const valid = r.valid === true && sample.mean_c !== null && sample.max_c !== null && sample.min_c !== null;
  return { state: r.state as SmartState, valid, over_range: r.over_range === true, sample, rings, dims: valid ? asDims(r.dims) : null };
}

/** The spec §3 state text. */
export function smartBadge(state: SmartState): string {
  if (state === "searching") return "searching… (not locked yet)";
  return state === "holding" ? "holding — edge lost" : "locked";
}

/** °C: whole degrees from 100 up, one decimal below. */
function t(v: number | null): string {
  if (v === null) return "n/a";
  return Math.abs(v) >= 100 ? Math.round(v).toFixed(0) : v.toFixed(1);
}
const temps = (s: SmartStats): string =>
  s.mean_c === null && s.max_c === null && s.min_c === null ? "n/a" : `mean ${t(s.mean_c)} °C · max ${t(s.max_c)} · min ${t(s.min_c)}`;
const pct = (v: number | null): string => {
  if (v === null) return "n/a";
  const r = Math.abs(v).toFixed(1);
  return `${v < 0 && Number(r) !== 0 ? "−" : "+"}${r} %`;  // a change that rounds to zero is +0.0
};

/** Readout lines for one smart ROI: state + sample numbers, one line per ring band, then the
 *  dimensions labelled as measured from the thermal edge (spec §5). Holding is valid (spec §7b) and
 *  keeps its numbers; an invalid entry shows only its status, never a number. */
export function smartReadoutLines(e: SmartReadoutEntry): string[] {
  const badge = smartBadge(e.state);
  if (!e.valid) {
    if (e.state === "searching") return [badge];
    return [`${badge} · not valid${e.over_range ? " (over-range pixels)" : ""}`];
  }
  const d = e.dims;
  const lines = [`${badge} · ${temps(e.sample)}${d ? ` · area ${d.area_px} px` : ""}`];
  for (const g of e.rings) lines.push(`ring ${g.inner_px}–${g.outer_px} px · ${temps(g)}`);
  if (!d) return lines;
  const sharp = d.sharpness_c_per_px === null ? "n/a" : `${d.sharpness_c_per_px.toFixed(2)} °C/px`;
  lines.push(`size (thermal edge, px) · length ${d.length_px.toFixed(1)} · width ${d.width_px.toFixed(1)} · perimeter ${d.perimeter_px} · sharpness ${sharp}`);
  lines.push(`change since first lock · area ${pct(d.area_change_pct)} · length ${pct(d.length_change_pct)} · width ${pct(d.width_change_pct)}`);
  lines.push(`centroid ${d.centroid_x.toFixed(1)}, ${d.centroid_y.toFixed(1)} px`);
  return lines;
}

/** The smart entries of a GET /api/live/roi-temps payload, by ROI id. */
export function smartFeedMap(payload: unknown): Map<number, SmartReadoutEntry> {
  const out = new Map<number, SmartReadoutEntry>();
  const rois = payload && typeof payload === "object" ? (payload as { rois?: unknown }).rois : null;
  if (!Array.isArray(rois)) return out;
  for (const raw of rois) {
    const id = (raw as { id?: unknown } | null)?.id;
    if (typeof id !== "number" || !Number.isInteger(id)) continue;
    const e = smartEntryFromFeed(raw);
    if (e) out.set(id, e);
  }
  return out;
}

/** On-image chip text (`muted`: dot in --muted, not the ROI colour, when not valid): state from the frame's overlay (per frame), numbers from the operator's feed
 *  only when it reports the same state and is valid (the polled feed may lag the frames). A stale
 *  stored outline (playback: the ROI changed since its series was computed) is muted, numberless. */
export function smartChip(draw: { state: SmartState; valid: boolean; stale?: boolean } | undefined, feed: SmartReadoutEntry | undefined): { value: string; range: string | null; muted: boolean } {
  const cur = draw ?? feed;
  if (!cur) return { value: "no outline", range: null, muted: true };
  if (draw?.stale) return { value: `${smartBadge(draw.state)} · stale`, range: null, muted: true };
  const value = cur.valid || cur.state === "searching" ? smartBadge(cur.state) : `${smartBadge(cur.state)} · not valid`;
  const s = feed && feed.valid && feed.state === cur.state && cur.valid ? feed.sample : null;
  return { value, range: s && s.mean_c !== null && s.max_c !== null ? `mean ${s.mean_c.toFixed(1)}  max ${s.max_c.toFixed(1)}` : null, muted: !cur.valid };
}
