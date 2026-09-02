/**
 * Regions of interest (spec §3, Milestone 6): spots and half-open rectangles in image pixel
 * coordinates (x = column, y = row, origin top-left). Statistics mirror backend
 * analysis/stats.py: NaN pixels are ignored and counted.
 */

export interface Spot { id: number; kind: "spot"; x: number; y: number; }
export interface Rect { id: number; kind: "rect"; x0: number; y0: number; x1: number; y1: number; }
export type Roi = Spot | Rect;
export type RoiInput = Omit<Spot, "id"> | Omit<Rect, "id">;

export interface RoiState { rois: Roi[]; selected: number | null; nextId: number; }
export const EMPTY_ROIS: RoiState = Object.freeze({ rois: [], selected: null, nextId: 1 }) as RoiState;

export type RoiAction =
  | { type: "add"; roi: RoiInput }
  | { type: "remove"; id: number }
  | { type: "select"; id: number | null }
  | { type: "clear" };

/** Applies one RoiAction without mutating the input; ids are never reused. */
export function roiReducer(s: RoiState, a: RoiAction): RoiState {
  switch (a.type) {
    case "add": {
      const roi = { ...a.roi, id: s.nextId } as Roi;
      return { rois: [...s.rois, roi], selected: roi.id, nextId: s.nextId + 1 };
    }
    case "remove": {
      const rois = s.rois.filter((r) => r.id !== a.id);
      return { ...s, rois, selected: s.selected === a.id ? null : s.selected };
    }
    case "select":
      return { ...s, selected: a.id !== null && s.rois.some((r) => r.id === a.id) ? a.id : null };
    case "clear":
      return { ...s, rois: [], selected: null };
  }
}

/** Orders two drag corners into a half-open rect clamped to the image; null if empty. */
export function normalizeRect(xa: number, ya: number, xb: number, yb: number, w: number, h: number): Omit<Rect, "id" | "kind"> | null {
  const x0 = Math.max(0, Math.min(xa, xb));
  const y0 = Math.max(0, Math.min(ya, yb));
  const x1 = Math.min(w, Math.max(xa, xb));
  const y1 = Math.min(h, Math.max(ya, yb));
  if (!(x1 > x0 && y1 > y0)) return null;
  return { x0, y0, x1, y1 };
}

export interface RoiStats { n: number; nan: number; min: number | null; max: number | null; mean: number | null; }
const NONE = (nan: number): RoiStats => ({ n: 0, nan, min: null, max: null, mean: null });

/** Statistics of `field` (row-major w×h) inside `roi`. Out-of-image pixels count as absent. */
export function roiStats(field: Float32Array, w: number, h: number, roi: Roi): RoiStats {
  if (roi.kind === "spot") {
    if (roi.x < 0 || roi.y < 0 || roi.x >= w || roi.y >= h) return NONE(0);
    const v = field[roi.y * w + roi.x];
    return Number.isNaN(v) ? NONE(1) : { n: 1, nan: 0, min: v, max: v, mean: v };
  }
  const x0 = Math.max(0, roi.x0), y0 = Math.max(0, roi.y0);
  const x1 = Math.min(w, roi.x1), y1 = Math.min(h, roi.y1);
  let n = 0, nan = 0, min = Infinity, max = -Infinity, sum = 0;
  for (let y = y0; y < y1; y++) {
    const row = y * w;
    for (let x = x0; x < x1; x++) {
      const v = field[row + x];
      if (Number.isNaN(v)) { nan++; continue; }
      n++; sum += v;
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  return n === 0 ? NONE(nan) : { n, nan, min, max, mean: sum / n };
}

export function roiLabel(roi: Roi): string {
  return `${roi.kind === "spot" ? "S" : "R"}${roi.id}`;
}

const KEY = "fri.rois.v1";

function isInt(v: unknown): v is number { return typeof v === "number" && Number.isInteger(v); }

function asRoi(v: unknown): Roi | null {
  if (!v || typeof v !== "object") return null;
  const r = v as Record<string, unknown>;
  if (!isInt(r.id) || r.id < 1) return null;
  if (r.kind === "spot" && isInt(r.x) && isInt(r.y)) return { id: r.id, kind: "spot", x: r.x, y: r.y };
  if (r.kind === "rect" && isInt(r.x0) && isInt(r.y0) && isInt(r.x1) && isInt(r.y1) && r.x1 > r.x0 && r.y1 > r.y0) {
    return { id: r.id, kind: "rect", x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
  }
  return null;
}

/** Reads persisted ROIs; anything malformed falls back to EMPTY_ROIS. Selection is never persisted. */
export function loadRois(storage: Storage | null): RoiState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return EMPTY_ROIS;
    const parsed = JSON.parse(raw) as { rois?: unknown; nextId?: unknown };
    const rois = Array.isArray(parsed.rois) ? parsed.rois.map(asRoi).filter((r): r is Roi => r !== null) : [];
    const maxId = rois.reduce((m, r) => Math.max(m, r.id), 0);
    const nextId = isInt(parsed.nextId) && parsed.nextId > maxId ? parsed.nextId : maxId + 1;
    return { rois, selected: null, nextId };
  } catch {
    return EMPTY_ROIS;
  }
}

export function saveRois(storage: Storage | null, s: RoiState): void {
  try { storage?.setItem(KEY, JSON.stringify({ rois: s.rois, nextId: s.nextId })); } catch { /* ignore */ }
}
