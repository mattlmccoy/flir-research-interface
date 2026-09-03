import { recorrectCelsius, type Radiometry } from "./emissivity.ts";
/**
 * Regions of interest (spec §3, Milestone 6): spots and half-open rectangles in image pixel
 * coordinates (x = column, y = row, origin top-left). Statistics mirror backend
 * analysis/stats.py: NaN pixels are ignored and counted.
 */

/** Optional presentation fields every ROI may carry. */
interface Meta {
  name?: string;
  color?: string;
  /** Not drawn and not selectable; still measured, recorded and exported. */
  hidden?: boolean;
  /** Per-ROI emissivity (0.01–1); values are re-corrected from the camera's global setting. */
  emissivity?: number;
  /** Per-ROI reflected temperature in °C (defaults to the camera's setting). */
  reflected_c?: number;
}
/** `box: 3` turns the spot into ResearchIR's measurement cursor: the mean of the 3×3 neighbourhood. */
export interface Spot extends Meta { id: number; kind: "spot"; x: number; y: number; box?: 1 | 3; }
export interface Rect extends Meta { id: number; kind: "rect"; x0: number; y0: number; x1: number; y1: number; }
/** Disc of radius r (pixels) around (cx, cy); a pixel belongs when its centre is within r. */
export interface Circle extends Meta { id: number; kind: "circle"; cx: number; cy: number; r: number; }
/** Axis-aligned ellipse: a pixel belongs when (dx/rx)² + (dy/ry)² ≤ 1 for its centre. */
export interface Ellipse extends Meta { id: number; kind: "ellipse"; cx: number; cy: number; rx: number; ry: number; }
/** Segment from (x0, y0) to (x1, y1), both endpoints inclusive, sampled with Bresenham. */
export interface Line extends Meta { id: number; kind: "line"; x0: number; y0: number; x1: number; y1: number; }
/** Closed polygon through `points` (≥ 3); pixels inside (even-odd) or on the boundary belong. */
export interface Polygon extends Meta { id: number; kind: "polygon"; points: [number, number][]; }
export type Roi = Spot | Rect | Circle | Ellipse | Line | Polygon;
export type RoiInput = Omit<Spot, "id"> | Omit<Rect, "id"> | Omit<Circle, "id"> | Omit<Ellipse, "id"> | Omit<Line, "id"> | Omit<Polygon, "id">;
/** Kinds whose stats are a mean/min/max over several pixels (everything but a spot). */
export function isArea(roi: Roi): boolean { return roi.kind !== "spot"; }

export interface RoiState { rois: Roi[]; selected: number | null; nextId: number; }
export const EMPTY_ROIS: RoiState = Object.freeze({ rois: [], selected: null, nextId: 1 }) as RoiState;

export type RoiAction =
  | { type: "add"; roi: RoiInput }
  | { type: "remove"; id: number }
  | { type: "select"; id: number | null }
  | { type: "move"; id: number; dx: number; dy: number }
  | { type: "rename"; id: number; name: string }
  | { type: "recolor"; id: number; color: string | null }
  | { type: "toggleHidden"; id: number }
  | { type: "setOptics"; id: number; emissivity?: number | null; reflected_c?: number | null }
  | { type: "setBox"; id: number; box: 1 | 3 }
  | { type: "setHiddenAll"; hidden: boolean }
  | { type: "replace"; rois: Roi[] }
  | { type: "clear" };

/** The ROIs that should be drawn and hit-tested. */
export function visibleRois(rois: Roi[]): Roi[] { return rois.filter((r) => !r.hidden); }

/** The same shape shifted by (dx, dy); shifts are clamped so no coordinate goes below zero. */
export function moveRoi(roi: Roi, dx: number, dy: number): Roi {
  const xs = (r: Roi): number[] => r.kind === "spot" ? [r.x] : r.kind === "circle" || r.kind === "ellipse" ? [r.cx] : r.kind === "polygon" ? r.points.map((p) => p[0]) : [r.x0, r.x1];
  const ys = (r: Roi): number[] => r.kind === "spot" ? [r.y] : r.kind === "circle" || r.kind === "ellipse" ? [r.cy] : r.kind === "polygon" ? r.points.map((p) => p[1]) : [r.y0, r.y1];
  const ddx = Math.max(dx, -Math.min(...xs(roi)));
  const ddy = Math.max(dy, -Math.min(...ys(roi)));
  switch (roi.kind) {
    case "spot": return { ...roi, x: roi.x + ddx, y: roi.y + ddy };
    case "circle": case "ellipse": return { ...roi, cx: roi.cx + ddx, cy: roi.cy + ddy };
    case "rect": case "line": return { ...roi, x0: roi.x0 + ddx, y0: roi.y0 + ddy, x1: roi.x1 + ddx, y1: roi.y1 + ddy };
    case "polygon": return { ...roi, points: roi.points.map(([x, y]) => [x + ddx, y + ddy] as [number, number]) };
  }
}

function patch(s: RoiState, id: number, f: (r: Roi) => Roi): RoiState {
  return { ...s, rois: s.rois.map((r) => (r.id === id ? f(r) : r)) };
}

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
    case "move":
      return patch(s, a.id, (r) => moveRoi(r, a.dx, a.dy));
    case "rename":
      return patch(s, a.id, (r) => { const name = a.name.trim(); const { name: _old, ...rest } = r; return name ? { ...rest, name } as Roi : rest as Roi; });
    case "recolor":
      return patch(s, a.id, (r) => { const { color: _old, ...rest } = r; return a.color ? { ...rest, color: a.color } as Roi : rest as Roi; });
    case "setBox":
      return patch(s, a.id, (r) => { if (r.kind !== "spot") return r; const { box: _b, ...rest } = r; return a.box === 3 ? { ...rest, box: 3 } as Roi : rest as Roi; });
    case "setOptics":
      return patch(s, a.id, (r) => {
        const { emissivity: e0, reflected_c: t0, ...rest } = r;
        const next: Roi = rest as Roi;
        const e = a.emissivity === undefined ? e0 : a.emissivity;
        const t = a.reflected_c === undefined ? t0 : a.reflected_c;
        if (typeof e === "number" && e > 0 && e <= 1) next.emissivity = e;
        else if (e !== null && e0 !== undefined) next.emissivity = e0;
        if (typeof t === "number" && Number.isFinite(t)) next.reflected_c = t;
        return next;
      });
    case "toggleHidden": {
      const next = patch(s, a.id, (r) => { const { hidden, ...rest } = r; return hidden ? rest as Roi : { ...rest, hidden: true } as Roi; });
      return next.rois.find((r) => r.id === a.id)?.hidden && s.selected === a.id ? { ...next, selected: null } : next;
    }
    case "setHiddenAll":
      return { ...s, rois: s.rois.map((r) => { const { hidden, ...rest } = r; return a.hidden ? { ...rest, hidden: true } as Roi : rest as Roi; }), selected: a.hidden ? null : s.selected };
    case "replace": {
      const maxId = a.rois.reduce((m, r) => Math.max(m, r.id), 0);
      return { rois: a.rois, selected: null, nextId: Math.max(s.nextId, maxId + 1) };
    }
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

export interface RoiStats {
  n: number; nan: number; min: number | null; max: number | null; mean: number | null;
  /** Image coordinates [x, y] of the hottest / coldest pixel (area ROIs only). */
  maxAt?: [number, number]; minAt?: [number, number];
  /** Population standard deviation (area ROIs). */
  std?: number;
}
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

/** Even-odd point-in-polygon test on pixel centres; boundary pixels (Bresenham edges) are included. */
export function polygonPixels(points: [number, number][], w: number, h: number): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  const push = (x: number, y: number) => { if (x < 0 || y < 0 || x >= w || y >= h) return; const k = y * w + x; if (!seen.has(k)) { seen.add(k); out.push(k); } };
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const [ax, ay] = points[i], [bx, by] = points[(i + 1) % n];
    for (const [x, y] of linePixels(ax, ay, bx, by)) push(x, y);
  }
  const minY = Math.max(0, Math.min(...points.map((p) => p[1]))), maxY = Math.min(h - 1, Math.max(...points.map((p) => p[1])));
  const minX = Math.max(0, Math.min(...points.map((p) => p[0]))), maxX = Math.min(w - 1, Math.max(...points.map((p) => p[0])));
  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      let inside = false;
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const [xi, yi] = points[i], [xj, yj] = points[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
      if (inside) push(x, y);
    }
  }
  return out;
}

/** Every pixel index (y*w+x) the ROI covers inside a w×h image, without duplicates. */
export function roiPixels(roi: Roi, w: number, h: number): number[] {
  const inside = (x: number, y: number) => x >= 0 && y >= 0 && x < w && y < h;
  switch (roi.kind) {
    case "spot": {
      if (roi.box !== 3) return inside(roi.x, roi.y) ? [roi.y * w + roi.x] : [];
      const out: number[] = [];
      for (let y = roi.y - 1; y <= roi.y + 1; y++) for (let x = roi.x - 1; x <= roi.x + 1; x++) if (inside(x, y)) out.push(y * w + x);
      return out;
    }
    case "rect": {
      const out: number[] = [];
      for (let y = Math.max(0, roi.y0); y < Math.min(h, roi.y1); y++) for (let x = Math.max(0, roi.x0); x < Math.min(w, roi.x1); x++) out.push(y * w + x);
      return out;
    }
    case "ellipse": {
      const out: number[] = [];
      for (let y = Math.max(0, Math.floor(roi.cy - roi.ry)); y <= Math.min(h - 1, Math.ceil(roi.cy + roi.ry)); y++) {
        for (let x = Math.max(0, Math.floor(roi.cx - roi.rx)); x <= Math.min(w - 1, Math.ceil(roi.cx + roi.rx)); x++) {
          const dx = (x - roi.cx) / roi.rx, dy = (y - roi.cy) / roi.ry;
          if (dx * dx + dy * dy <= 1) out.push(y * w + x);
        }
      }
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
    case "polygon":
      return polygonPixels(roi.points, w, h);
  }
}

/** Statistics of `field` (row-major w×h) inside `roi`. Out-of-image pixels count as absent. */
export function roiStats(field: Float32Array, w: number, h: number, roi: Roi, rad?: Radiometry | null): RoiStats {
  let n = 0, nan = 0, min = Infinity, max = -Infinity, sum = 0, sq = 0, kMin = -1, kMax = -1;
  const eps = roi.emissivity;
  const correct = rad && eps !== undefined && eps > 0 && eps <= 1;
  const treflK = (roi.reflected_c ?? (rad ? rad.treflCamK - 273.15 : 0)) + 273.15;
  for (const k of roiPixels(roi, w, h)) {
    const v = correct ? recorrectCelsius(field[k], rad, eps, treflK) : field[k];
    if (Number.isNaN(v)) { nan++; continue; }
    n++; sum += v; sq += v * v;
    if (v < min) { min = v; kMin = k; }
    if (v > max) { max = v; kMax = k; }
  }
  if (n === 0) return NONE(nan);
  const out: RoiStats = { n, nan, min, max, mean: sum / n };
  if (roi.kind !== "spot") {
    out.maxAt = [kMax % w, Math.floor(kMax / w)]; out.minAt = [kMin % w, Math.floor(kMin / w)];
    out.std = Math.sqrt(Math.max(0, sq / n - (sum / n) * (sum / n)));
  }
  return out;
}

const PREFIX: Record<Roi["kind"], string> = { spot: "S", rect: "R", circle: "C", ellipse: "E", line: "L", polygon: "P" };
/** The user's name when set, else a short id like S1 / R2 / C3 / L4 / P5. */
export function roiLabel(roi: Roi): string {
  return roi.name || `${PREFIX[roi.kind]}${roi.id}`;
}
export function roiId(roi: Roi): string {
  return `${PREFIX[roi.kind]}${roi.id}`;
}

const KEY = "fri.rois.v1";

function isInt(v: unknown): v is number { return typeof v === "number" && Number.isInteger(v); }

const HEX = /^#[0-9a-f]{6}$/i;

function asRoi(v: unknown): Roi | null {
  if (!v || typeof v !== "object") return null;
  const r = v as Record<string, unknown>;
  if (!isInt(r.id) || r.id < 1) return null;
  const meta: Meta = {};
  if (typeof r.name === "string" && r.name.trim()) meta.name = r.name.trim().slice(0, 40);
  if (typeof r.color === "string" && HEX.test(r.color)) meta.color = r.color.toLowerCase();
  if (r.hidden === true) meta.hidden = true;
  if (r.box === 3) (meta as { box?: 3 }).box = 3;
  if (typeof r.emissivity === "number" && r.emissivity > 0 && r.emissivity <= 1) meta.emissivity = r.emissivity;
  if (typeof r.reflected_c === "number" && Number.isFinite(r.reflected_c)) meta.reflected_c = r.reflected_c;
  let shape: Roi | null = null;
  if (r.kind === "spot" && isInt(r.x) && isInt(r.y)) shape = { id: r.id, kind: "spot", x: r.x, y: r.y };
  else if (r.kind === "rect" && isInt(r.x0) && isInt(r.y0) && isInt(r.x1) && isInt(r.y1) && r.x1 > r.x0 && r.y1 > r.y0) {
    shape = { id: r.id, kind: "rect", x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
  } else if (r.kind === "circle" && isInt(r.cx) && isInt(r.cy) && typeof r.r === "number" && Number.isFinite(r.r) && r.r >= 1) {
    shape = { id: r.id, kind: "circle", cx: r.cx, cy: r.cy, r: r.r };
  } else if (r.kind === "ellipse" && isInt(r.cx) && isInt(r.cy) && typeof r.rx === "number" && typeof r.ry === "number" && r.rx >= 1 && r.ry >= 1) {
    shape = { id: r.id, kind: "ellipse", cx: r.cx, cy: r.cy, rx: r.rx, ry: r.ry };
  } else if (r.kind === "line" && isInt(r.x0) && isInt(r.y0) && isInt(r.x1) && isInt(r.y1) && (r.x0 !== r.x1 || r.y0 !== r.y1)) {
    shape = { id: r.id, kind: "line", x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
  } else if (r.kind === "polygon" && Array.isArray(r.points) && r.points.length >= 3 && r.points.every((p) => Array.isArray(p) && p.length === 2 && isInt(p[0]) && isInt(p[1]))) {
    shape = { id: r.id, kind: "polygon", points: r.points.map((p) => [p[0], p[1]] as [number, number]) };
  }
  return shape ? { ...shape, ...meta } : null;
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
