/**
 * Regions of interest (spec §3, Milestone 6): spots and half-open rectangles in image pixel
 * coordinates (x = column, y = row, origin top-left). Statistics mirror backend
 * analysis/stats.py: NaN pixels are ignored and counted.
 */

export interface Spot { id: number; kind: "spot"; x: number; y: number; }
export interface Rect { id: number; kind: "rect"; x0: number; y0: number; x1: number; y1: number; }
/** Disc of radius r (pixels) around (cx, cy); a pixel belongs when its centre is within r. */
export interface Circle { id: number; kind: "circle"; cx: number; cy: number; r: number; }
/** Segment from (x0, y0) to (x1, y1), both endpoints inclusive, sampled with Bresenham. */
export interface Line { id: number; kind: "line"; x0: number; y0: number; x1: number; y1: number; }
/** Connected segments through `points` (≥ 2); joints are counted once. */
export interface Polyline { id: number; kind: "polyline"; points: [number, number][]; }
export type Roi = Spot | Rect | Circle | Line | Polyline;
export type RoiInput = Omit<Spot, "id"> | Omit<Rect, "id"> | Omit<Circle, "id"> | Omit<Line, "id"> | Omit<Polyline, "id">;
/** Kinds whose stats are a mean/min/max over several pixels (everything but a spot). */
export function isArea(roi: Roi): boolean { return roi.kind !== "spot"; }

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

/** Bresenham pixels from (x0,y0) to (x1,y1), both inclusive, no clipping. */
export function linePixels(x0: number, y0: number, x1: number, y1: number): [number, number][] {
  const out: [number, number][] = [];
  const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx + dy, x = x0, y = y0;
  for (;;) {
    out.push([x, y]);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x += sx; }
    if (e2 <= dx) { err += dx; y += sy; }
  }
  return out;
}

/** Every pixel index (y*w+x) the ROI covers inside a w×h image, without duplicates. */
export function roiPixels(roi: Roi, w: number, h: number): number[] {
  const inside = (x: number, y: number) => x >= 0 && y >= 0 && x < w && y < h;
  switch (roi.kind) {
    case "spot":
      return inside(roi.x, roi.y) ? [roi.y * w + roi.x] : [];
    case "rect": {
      const out: number[] = [];
      for (let y = Math.max(0, roi.y0); y < Math.min(h, roi.y1); y++) for (let x = Math.max(0, roi.x0); x < Math.min(w, roi.x1); x++) out.push(y * w + x);
      return out;
    }
    case "circle": {
      const out: number[] = [];
      const r2 = roi.r * roi.r;
      for (let y = Math.max(0, Math.floor(roi.cy - roi.r)); y <= Math.min(h - 1, Math.ceil(roi.cy + roi.r)); y++) {
        for (let x = Math.max(0, Math.floor(roi.cx - roi.r)); x <= Math.min(w - 1, Math.ceil(roi.cx + roi.r)); x++) {
          const dx = x - roi.cx, dy = y - roi.cy;
          if (dx * dx + dy * dy <= r2) out.push(y * w + x);
        }
      }
      return out;
    }
    case "line":
      return linePixels(roi.x0, roi.y0, roi.x1, roi.y1).filter(([x, y]) => inside(x, y)).map(([x, y]) => y * w + x);
    case "polyline": {
      const seen = new Set<number>();
      const out: number[] = [];
      for (let i = 1; i < roi.points.length; i++) {
        const [ax, ay] = roi.points[i - 1], [bx, by] = roi.points[i];
        for (const [x, y] of linePixels(ax, ay, bx, by)) {
          if (!inside(x, y)) continue;
          const k = y * w + x;
          if (!seen.has(k)) { seen.add(k); out.push(k); }
        }
      }
      return out;
    }
  }
}

/** Statistics of `field` (row-major w×h) inside `roi`. Out-of-image pixels count as absent. */
export function roiStats(field: Float32Array, w: number, h: number, roi: Roi): RoiStats {
  let n = 0, nan = 0, min = Infinity, max = -Infinity, sum = 0;
  for (const k of roiPixels(roi, w, h)) {
    const v = field[k];
    if (Number.isNaN(v)) { nan++; continue; }
    n++; sum += v;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return n === 0 ? NONE(nan) : { n, nan, min, max, mean: sum / n };
}

const PREFIX: Record<Roi["kind"], string> = { spot: "S", rect: "R", circle: "C", line: "L", polyline: "P" };
export function roiLabel(roi: Roi): string {
  return `${PREFIX[roi.kind]}${roi.id}`;
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
  if (r.kind === "circle" && isInt(r.cx) && isInt(r.cy) && typeof r.r === "number" && Number.isFinite(r.r) && r.r >= 1) {
    return { id: r.id, kind: "circle", cx: r.cx, cy: r.cy, r: r.r };
  }
  if (r.kind === "line" && isInt(r.x0) && isInt(r.y0) && isInt(r.x1) && isInt(r.y1) && (r.x0 !== r.x1 || r.y0 !== r.y1)) {
    return { id: r.id, kind: "line", x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
  }
  if (r.kind === "polyline" && Array.isArray(r.points) && r.points.length >= 2 && r.points.every((p) => Array.isArray(p) && p.length === 2 && isInt(p[0]) && isInt(p[1]))) {
    return { id: r.id, kind: "polyline", points: r.points.map((p) => [p[0], p[1]] as [number, number]) };
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
