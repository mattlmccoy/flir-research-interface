// A recorded run's stored smart ROI series (GET /api/experiments/{name}/smart-roi/{id}, backend
// analysis/smart_series.py series_payload + `stale`) and the playback readout / compute-job view
// built from it. Pure: fetching and polling live in components/useSmartSeries.ts.
import { smartReadoutLines, type SmartReadoutEntry, type SmartState } from "./smartReadout.ts";
import type { SmartRowView } from "./smartFeed.ts";
import { smartTracking, type Smart } from "./roi.ts";

type Col = (number | null)[];
export interface SmartSeriesRing { inner_px: number; outer_px: number; mean: Col; max: Col; min: Col; }
export interface SmartSeries {
  /** Frame index of each stored point (every stride-th frame when downsampled). */
  index: number[];
  t_s: number[];
  state: SmartState[];
  valid: boolean[];
  sample: { mean: Col; max: Col; min: Col };
  rings: SmartSeriesRing[];
  dims: Record<"area_px" | "length_px" | "width_px" | "perimeter_px" | "centroid_x" | "centroid_y" | "sharpness_c_per_px" | "area_change_pct" | "length_change_pct" | "width_change_pct", Col>;
  /** The run's ROI or frame count changed since the series was computed. */
  stale: boolean;
}
const DIM_KEYS = ["area_px", "length_px", "width_px", "perimeter_px", "centroid_x", "centroid_y", "sharpness_c_per_px", "area_change_pct", "length_change_pct", "width_change_pct"] as const;
const STATES: readonly SmartState[] = ["searching", "locked", "holding"];

/** Progress record of the compute job (POST …/compute, GET …/status). */
export interface SmartJob { state: "running" | "done" | "error" | "idle"; done: number; total: number; error: string | null; }

/** What playback knows about one smart ROI's stored series. */
export type SmartSeriesState =
  | { kind: "loading" }
  | { kind: "missing" }  // 404: not computed for this run
  | { kind: "error"; message: string }  // fetch failed for another reason (retryable)
  | { kind: "ready"; series: SmartSeries };

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object";
function col(v: unknown, n: number): Col | null {
  if (!Array.isArray(v) || v.length !== n) return null;
  return v.map((x) => (typeof x === "number" && Number.isFinite(x) ? x : null));
}

/** The payload as typed columns, or null when it is not a well-formed series. */
export function parseSmartSeries(raw: unknown): SmartSeries | null {
  if (!isObj(raw) || !Array.isArray(raw.index) || !Array.isArray(raw.t_s) || !Array.isArray(raw.state) || !Array.isArray(raw.valid)) return null;
  const n = raw.index.length;
  if (raw.t_s.length !== n || raw.state.length !== n || raw.valid.length !== n) return null;
  if (!raw.state.every((s) => STATES.includes(s as SmartState))) return null;
  if (!isObj(raw.sample) || !isObj(raw.dims) || !Array.isArray(raw.rings)) return null;
  const mean = col(raw.sample.mean, n), max = col(raw.sample.max, n), min = col(raw.sample.min, n);
  if (!mean || !max || !min) return null;
  const rings: SmartSeriesRing[] = [];
  for (const g of raw.rings) {
    if (!isObj(g) || typeof g.inner_px !== "number" || typeof g.outer_px !== "number") return null;
    const gm = col(g.mean, n), gx = col(g.max, n), gn = col(g.min, n);
    if (!gm || !gx || !gn) return null;
    rings.push({ inner_px: g.inner_px, outer_px: g.outer_px, mean: gm, max: gx, min: gn });
  }
  const dims = {} as SmartSeries["dims"];
  for (const k of DIM_KEYS) {
    const c = col(raw.dims[k], n);
    if (!c) return null;
    dims[k] = c;
  }
  return {
    index: raw.index.map(Number), t_s: raw.t_s.map(Number), state: raw.state as SmartState[],
    valid: raw.valid.map((v) => v === true), sample: { mean, max, min }, rings, dims, stale: raw.stale === true,
  };
}

/** True only for the API's 404 (lib/api.ts j() throws `${status} ${detail}`): not computed yet. */
export function isNotFound(e: unknown): boolean {
  return e instanceof Error && /^404\b/.test(e.message);
}

/** A row is a reading only when the tracker reported it valid and not searching (holding is valid). */
export function rowValid(s: SmartSeries, k: number): boolean {
  return s.valid[k] && s.state[k] !== "searching";
}

/** The stored row at frame `frame`, or the nearest earlier stored point when the series is
 *  downsampled (`exact` false); null before the first stored point. */
export function smartRowAt(s: SmartSeries, frame: number): { frame: number; exact: boolean; entry: SmartReadoutEntry } | null {
  let lo = 0, hi = s.index.length - 1, k = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (s.index[mid] <= frame) { k = mid; lo = mid + 1; } else hi = mid - 1;
  }
  if (k < 0) return null;
  const valid = rowValid(s, k) && s.sample.mean[k] !== null && s.sample.max[k] !== null && s.sample.min[k] !== null;
  const d = (key: keyof SmartSeries["dims"]) => s.dims[key][k];
  const req = [d("area_px"), d("length_px"), d("width_px"), d("perimeter_px"), d("centroid_x"), d("centroid_y")];
  const dims = valid && req.every((v) => v !== null) ? {
    area_px: d("area_px")!, length_px: d("length_px")!, width_px: d("width_px")!, perimeter_px: d("perimeter_px")!,
    centroid_x: d("centroid_x")!, centroid_y: d("centroid_y")!, sharpness_c_per_px: d("sharpness_c_per_px"),
    area_change_pct: d("area_change_pct"), length_change_pct: d("length_change_pct"), width_change_pct: d("width_change_pct"),
    units: "px" as const,
  } : null;
  const entry: SmartReadoutEntry = {
    state: s.state[k], valid, over_range: false,  // over-range is not part of the plot payload
    sample: { mean_c: s.sample.mean[k], max_c: s.sample.max[k], min_c: s.sample.min[k] },
    rings: s.rings.map((g) => ({ inner_px: g.inner_px, outer_px: g.outer_px, mean_c: g.mean[k], max_c: g.max[k], min_c: g.min[k] })),
    dims,
  };
  return { frame: s.index[k], exact: s.index[k] === frame, entry };
}

const none = (line: string): SmartRowView => ({ lines: [line], tone: "none", mean: null, marker: null });

/** Context for the playhead readout: `edited` = the on-screen ROI's tracking settings differ from
 *  the stored ones the series was computed from; `overlay` = the stored per-frame state at exactly
 *  this frame (from the overlay endpoint), when loaded. */
export interface SmartPlaybackCtx { edited?: boolean; overlay?: { state: SmartState; valid: boolean } | null; }

/** Playback rail readout for one smart ROI at frame `frame`, from its stored series. A stale or
 *  edited series and a downsampled (nearest-point) value are marked and never get the locked tone;
 *  the exact frame's overlay state, when known, gates the number. */
export function smartPlaybackRow(st: SmartSeriesState, frame: number, ctx: SmartPlaybackCtx = {}): SmartRowView {
  if (st.kind === "loading") return none("loading the stored smart ROI series…");
  if (st.kind === "missing") return none("not computed for this run yet: compute it to see its values");
  if (st.kind === "error") return none(`couldn’t load the stored series: ${st.message}`);
  const r = smartRowAt(st.series, frame);
  if (!r) return none("no stored reading at this frame");
  const ov = ctx.overlay;
  const e = ov && (!ov.valid || ov.state === "searching") && r.entry.valid
    ? { ...r.entry, state: ov.state, valid: false, dims: null }  // this exact frame is not a reading
    : r.entry;
  const lines = smartReadoutLines(e);
  if (!r.exact && e.valid) lines.push(`≈ values at frame ${r.frame + 1} (nearest stored point before frame ${frame + 1}; the plot series is downsampled)`);
  if (st.series.stale) lines.push("stale: the ROI or recording changed since this series was computed; recompute it");
  else if (ctx.edited) lines.push("stale: the ROI was edited on screen since this series was computed; recompute it");
  if (!e.valid) return { lines, tone: e.state === "searching" ? "searching" : "invalid", mean: null, marker: e.state === "searching" ? "searching" : "not valid" };
  const stale = st.series.stale || !!ctx.edited;
  const marks = [stale ? "stale" : null, r.exact ? null : "≈", e.state === "holding" ? "holding" : null].filter((m): m is string => m !== null);
  const tone = stale || !r.exact ? "invalid" : e.state === "holding" ? "holding" : "locked";
  return { lines, tone, mean: e.sample.mean_c, marker: marks.length ? marks.join(" ") : null };
}

export interface SmartComputeAction { label: string; kind: "compute" | "reload"; disabled: boolean; }

/** The button a smart ROI row offers: compute when missing, recompute when stale or edited on screen
 *  since (`edited`), retry after a failed fetch; nothing while loading or when fresh. */
export function smartComputeAction(st: SmartSeriesState, job: SmartJob | null, edited: boolean): SmartComputeAction | null {
  if (job?.state === "running") return { label: "computing…", kind: "compute", disabled: true };
  if (st.kind === "missing") return { label: "compute smart ROI", kind: "compute", disabled: false };
  if (st.kind === "error") return { label: "retry loading", kind: "reload", disabled: false };
  if (st.kind === "ready" && (st.series.stale || edited)) return { label: "recompute smart ROI", kind: "compute", disabled: false };
  return null;
}

/** Progress / failure text of the compute job (null when there is nothing to say). */
export function smartJobText(job: SmartJob | null): string | null {
  if (!job) return null;
  if (job.state === "running") {
    return job.total > 0 ? `computing… ${job.done}/${job.total} frames (${Math.round((100 * job.done) / job.total)} %)` : "computing…";
  }
  if (job.state === "error") return `compute failed: ${job.error ?? "unknown error"}`;
  return null;
}

/** True when the on-screen smart ROI is not stored with the run, or its tracking settings differ
 *  from the stored one (so a compute must first save the ROIs into the run). */
export function smartEdited(onScreen: Smart, stored: unknown[] | null | undefined): boolean {
  const s = (Array.isArray(stored) ? stored : []).find((x): x is Record<string, unknown> => isObj(x) && x.id === onScreen.id);
  if (!s || s.kind !== "smart") return true;
  return JSON.stringify(smartTracking(s)) !== JSON.stringify(smartTracking(onScreen as unknown as Record<string, unknown>));
}

export const SMART_POLL_MS = 700;
/** Consecutive failed status polls tolerated before the job is reported lost. */
export const SMART_POLL_TRIES = 3;
export interface SmartPollState { job: SmartJob | null; failures: number; }
export type SmartPollEvent = { ok: true; job: SmartJob } | { ok: false; error: string };

/** One status poll of the compute job: keep polling while running, reload the series when done,
 *  stop on error/idle. A failed poll is retried with a growing delay; after SMART_POLL_TRIES in a
 *  row the job becomes an error ("lost contact"), so the UI never sticks at "computing…". */
export function smartPollStep(prev: SmartPollState, ev: SmartPollEvent): { next: SmartPollState; action: "continue" | "reload" | "stop"; delayMs: number } {
  if (ev.ok) {
    const next = { job: ev.job, failures: 0 };
    if (ev.job.state === "running") return { next, action: "continue", delayMs: SMART_POLL_MS };
    return { next, action: ev.job.state === "done" ? "reload" : "stop", delayMs: 0 };
  }
  const failures = prev.failures + 1;
  if (failures < SMART_POLL_TRIES) return { next: { job: prev.job, failures }, action: "continue", delayMs: SMART_POLL_MS * 2 ** failures };
  const job: SmartJob = { state: "error", done: prev.job?.done ?? 0, total: prev.job?.total ?? 0, error: `lost contact with the compute job (${ev.error}); it may still be running on the operator` };
  return { next: { job, failures }, action: "stop", delayMs: 0 };
}

/** The run's stored ROI list with only `roi` saved into it (same id replaced, else appended); the
 *  other stored ROIs are kept exactly as stored. Used before computing an unsaved/edited smart ROI.
 *  Throws when `stored` is not an array: treating "unknown" as "empty" would PUT [roi] and wipe
 *  every other ROI stored with the run (a run with none stored passes []). */
export function upsertStoredRoi(stored: unknown[] | null | undefined, roi: Smart): unknown[] {
  if (!Array.isArray(stored)) throw new Error("upsertStoredRoi: the run's stored ROI list is not loaded");
  const list = stored;
  const at = list.findIndex((x) => isObj(x) && x.id === roi.id);
  return at < 0 ? [...list, roi] : list.map((x, k) => (k === at ? roi : x));
}
