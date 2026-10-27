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
/** Readings that stay honest while pixels are over range (backend smart_roi._over_stats): the
 *  over-range pixels counted at the camera's range top make `mean_lb_c` a lower bound; `min_c` is
 *  the exact in-range min (a bound only when `min_is_bound`); `max_c` is null whenever `over_px` > 0
 *  (the true max is above `ceiling_c`, null = range top unknown). With `over_px` 0 these are the
 *  region's plain numbers. */
export interface SmartOverStats {
  mean_lb_c: number | null; min_c: number | null; min_is_bound: boolean; max_c: number | null;
  over_px: number; ceiling_c: number | null;
}
/** The overlay's `over` block (live: WS frame `smart[i].over`; playback: the stored columns).
 *  UI only: the TC-POWER feed never carries these numbers. Rings pair with `rings` by position. */
export interface SmartOver { sample: SmartOverStats; rings: SmartOverStats[]; }
export interface SmartReadoutEntry {
  state: SmartState; valid: boolean; over_range: boolean;
  sample: SmartStats; rings: SmartRing[]; dims: SmartDims | null;
  /** Present while the sample or a ring has over-range pixels. */
  over?: SmartOver | null;
}

const STATES: readonly SmartState[] = ["searching", "locked", "holding"];
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const stats = (o: Record<string, unknown>): SmartStats => ({ mean_c: num(o.mean_c), max_c: num(o.max_c), min_c: num(o.min_c) });

function overStats(v: unknown): SmartOverStats | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const px = o.over_px;
  if (typeof px !== "number" || !Number.isInteger(px) || px < 0 || typeof o.min_is_bound !== "boolean") return null;
  const nullable = ["mean_lb_c", "min_c", "max_c", "ceiling_c"] as const;
  if (!nullable.every((k) => o[k] === null || num(o[k]) !== null)) return null;
  return { mean_lb_c: num(o.mean_lb_c), min_c: num(o.min_c), min_is_bound: o.min_is_bound, max_c: num(o.max_c), over_px: px, ceiling_c: num(o.ceiling_c) };
}

/** An overlay's `over` block, or null when absent or malformed (never a partial reading). */
export function parseSmartOver(raw: unknown): SmartOver | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const sample = overStats(r.sample);
  if (!sample || !Array.isArray(r.rings)) return null;
  const rings = r.rings.map(overStats);
  return rings.every((g): g is SmartOverStats => g !== null) ? { sample, rings } : null;
}

/** True when the entry is located (not searching) and its sample has over-range pixels with
 *  bounded readings to show. */
export function isOverRange(e: SmartReadoutEntry): boolean {
  return e.state !== "searching" && !!e.over && e.over.sample.over_px > 0;
}

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
/** `max > 250 (over range)`, or `max over range` when the range top is unknown. */
const overMax = (o: SmartOverStats): string => (o.ceiling_c === null ? "max over range" : `max > ${t(o.ceiling_c)} (over range)`);
/** A region with over-range pixels: lower-bound mean, exact (or bound) min, max above the range.
 *  Padded like the summary so the row keeps its shape; `min ≥` only when no pixel is in range. */
const bounded = (o: SmartOverStats): string =>
  `mean ≥ ${pad(t(o.mean_lb_c), 5)} °C · min ${o.min_is_bound ? "≥ " : ""}${pad(t(o.min_c), 5)} · ${overMax(o)}`;
/** A region's numbers from its over block: bounded when it has over-range pixels, plain otherwise. */
const overTemps = (o: SmartOverStats): string =>
  o.over_px > 0 ? `${bounded(o)} · ${o.over_px} px` : temps({ mean_c: o.mean_lb_c, max_c: o.max_c, min_c: o.min_c });
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
  if (isOverRange(e)) return [smartSummary(e)];
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

/** The collapsed rail row: one line, state · sample mean · max · area. Not valid: the badge text
 *  only (the same status as smartReadoutLines), never a number. */
export function smartSummary(e: SmartReadoutEntry): string {
  if (isOverRange(e)) return `${smartBadge(e.state)} · ${bounded(e.over!.sample)}`;
  if (!e.valid) return smartReadoutLines(e)[0];
  const d = e.dims;
  return `${smartBadge(e.state)} · ${pad(t(e.sample.mean_c), 5)} °C · max ${pad(t(e.sample.max_c), 5)}${d ? ` · area ${pad(String(d.area_px), 6)} px` : ""}`;
}

/** Left-pads a number with figure spaces (digit-wide) so the collapsed row keeps one shape from
 *  frame to frame (with tabular-nums in CSS nothing shifts). */
const pad = (s: string, w: number): string => s.padStart(w, "\u2007");

export interface SmartDetailRow { label: string; value: string; }

/** The expanded rail row as label/value rows: sample, each shown ring band (`hiddenRings` = outer
 *  offsets left out), then the thermal-edge size. Not valid: no rows (no numbers). */
export function smartDetails(e: SmartReadoutEntry, hiddenRings: readonly number[] = []): SmartDetailRow[] {
  const over = isOverRange(e) ? e.over! : null;
  if (!e.valid && !over) return [];
  const rows: SmartDetailRow[] = over
    ? [{ label: "sample", value: bounded(over.sample) }, { label: "over-range px", value: `${over.sample.over_px} px` }]
    : [{ label: "sample", value: temps(e.sample) }];
  e.rings.forEach((g, q) => {
    if (hiddenRings.includes(g.outer_px)) return;
    // a ring's own over block (live: the overlay; playback: the stored columns) when it has one:
    // bounded where the ring has over-range pixels, else its plain numbers
    const go = e.over?.rings[q];
    const value = go && (over || go.over_px > 0) ? overTemps(go) : temps(g);
    rows.push({ label: `ring ${g.inner_px}–${g.outer_px} px`, value });
  });
  const d = e.dims;
  if (!d) return rows;
  // one short value per row: a long row would wrap differently as its digits change frame to frame
  rows.push(
    { label: "length (edge)", value: `${d.length_px.toFixed(1)} px` },
    { label: "width (edge)", value: `${d.width_px.toFixed(1)} px` },
    { label: "perimeter", value: `${d.perimeter_px} px` },
    { label: "sharpness", value: d.sharpness_c_per_px === null ? "n/a" : `${d.sharpness_c_per_px.toFixed(2)} °C/px` },
    { label: "Δ area", value: pct(d.area_change_pct) },
    { label: "Δ length", value: pct(d.length_change_pct) },
    { label: "Δ width", value: pct(d.width_change_pct) },
    { label: "centroid", value: `${d.centroid_x.toFixed(1)}, ${d.centroid_y.toFixed(1)} px` },
  );
  return rows;
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
export function smartChip(draw: { state: SmartState; valid: boolean; stale?: boolean; over?: SmartOver | null } | undefined, feed: SmartReadoutEntry | undefined): { value: string; range: string | null; muted: boolean; warn?: true } {
  const cur = draw ?? feed;
  if (!cur) return { value: "no outline", range: null, muted: true };
  if (draw?.stale) return { value: `${smartBadge(draw.state)} · stale`, range: null, muted: true };
  // over range at this frame (the overlay's own block, never the feed): the bound, in warn
  const o = draw && draw.state !== "searching" && draw.over && draw.over.sample.over_px > 0 ? draw.over.sample : null;
  if (o) {
    const max = o.ceiling_c === null ? "max over range" : `max > ${Math.round(o.ceiling_c)}`;
    return { value: `${smartBadge(draw!.state)} · over range`, range: o.mean_lb_c === null ? max : `mean ≥ ${o.mean_lb_c.toFixed(1)}  ${max}`, muted: false, warn: true };
  }
  const value = cur.valid || cur.state === "searching" ? smartBadge(cur.state) : `${smartBadge(cur.state)} · not valid`;
  const s = feed && feed.valid && feed.state === cur.state && cur.valid ? feed.sample : null;
  return { value, range: s && s.mean_c !== null && s.max_c !== null ? `mean ${s.mean_c.toFixed(1)}  max ${s.max_c.toFixed(1)}` : null, muted: !cur.valid };
}
