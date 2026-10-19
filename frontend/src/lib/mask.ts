/**
 * Region masks: include/exclude polygons and rectangles that pick which pixels drive the colour
 * auto-range and the frame statistics. Display/analysis aid only: the recorded counts are never
 * touched, and masks are not ROIs (no readout, no series). Coverage reuses the ROI rasteriser, so a
 * mask rect or polygon covers exactly the pixels the same ROI would.
 */
import { roiPixels, roiReducer, type Polygon, type Rect, type Roi, type RoiAction } from "./roi.ts";
import type { Tool } from "./layout.ts";

/** Tools that draw a mask region. */
export const MASK_DRAW_TOOLS: readonly Tool[] = ["rect", "polygon", "freehand"];

/** The tool to use on entering mask mode: keep a mask-drawing tool, otherwise the rectangle
 *  (the select tool would only pick, so the first drag would draw nothing). */
export function toolForMaskMode(tool: Tool): Tool {
  return MASK_DRAW_TOOLS.includes(tool) ? tool : "rect";
}

export type MaskMode = "include" | "exclude";
export type MaskShape =
  | ({ id: number; mode: MaskMode } & Pick<Rect, "kind" | "x0" | "y0" | "x1" | "y1">)
  | ({ id: number; mode: MaskMode } & Pick<Polygon, "kind" | "points">);
export type MaskGeometry =
  | Pick<Rect, "kind" | "x0" | "y0" | "x1" | "y1">
  | Pick<Polygon, "kind" | "points">;

export interface MaskState { shapes: MaskShape[]; enabled: boolean; drawMode: MaskMode; nextId: number; selected: number | null; selectedIds: number[]; }
export const EMPTY_MASKS: MaskState = Object.freeze({ shapes: [], enabled: true, drawMode: "exclude", nextId: 1, selected: null, selectedIds: [] }) as MaskState;

export type MaskAction =
  | { type: "add"; shape: MaskGeometry }
  | { type: "remove"; id: number }
  | { type: "toggleMode"; id: number }
  | { type: "setEnabled"; enabled: boolean }
  | { type: "setDrawMode"; mode: MaskMode }
  | { type: "clear" }
  | { type: "load"; shapes: unknown[] }
  /** An ROI editing action (select / move / setVertex / remove …) applied to the mask regions. */
  | { type: "edit"; action: RoiAction };

/** Outline colours on the editing canvas (match the --mask-include / --mask-exclude tokens). */
const MASK_COLOR: Record<MaskMode, string> = { include: "#5cff8a", exclude: "#ff5f56" };

/** The regions as ROIs for the image's editing layer: same handles, move and delete as ROIs. */
export function masksAsRois(shapes: readonly MaskShape[]): Roi[] {
  return shapes.map(({ mode, ...geo }) => ({ ...geo, name: `${mode} ${geo.id}`, color: MASK_COLOR[mode] }) as Roi);
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** A stored/received shape, or null when it cannot be rasterised (unknown kind, bad geometry). */
export function asMask(x: unknown): MaskShape | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  if (!isNum(o.id) || (o.mode !== "include" && o.mode !== "exclude")) return null;
  if (o.kind === "rect" && isNum(o.x0) && isNum(o.y0) && isNum(o.x1) && isNum(o.y1)) {
    return { id: o.id, kind: "rect", x0: o.x0, y0: o.y0, x1: o.x1, y1: o.y1, mode: o.mode };
  }
  if (o.kind === "polygon" && Array.isArray(o.points) && o.points.length >= 3
    && o.points.every((p) => Array.isArray(p) && p.length === 2 && isNum(p[0]) && isNum(p[1]))) {
    return { id: o.id, kind: "polygon", points: (o.points as [number, number][]).map(([a, b]) => [a, b]), mode: o.mode };
  }
  return null;
}

export function maskReducer(s: MaskState, a: MaskAction): MaskState {
  switch (a.type) {
    case "add":
      return { ...s, shapes: [...s.shapes, { ...a.shape, id: s.nextId, mode: s.drawMode } as MaskShape], nextId: s.nextId + 1 };
    case "remove": {
      const drop = (id: number | null) => (id === a.id ? null : id);
      return { ...s, shapes: s.shapes.filter((m) => m.id !== a.id), selected: drop(s.selected), selectedIds: s.selectedIds.filter((i) => i !== a.id) };
    }
    case "edit": {
      if (a.action.type === "add") return s;  // new regions come through "add" with the draw mode
      const out = roiReducer({ rois: masksAsRois(s.shapes), selected: s.selected, selectedIds: s.selectedIds, nextId: s.nextId }, a.action);
      const modeOf = new Map(s.shapes.map((m) => [m.id, m.mode]));
      const shapes = out.rois.map((r) => asMask({ ...r, mode: modeOf.get(r.id) })).filter((m): m is MaskShape => m !== null);
      return { ...s, shapes, selected: out.selected, selectedIds: out.selectedIds };
    }
    case "toggleMode":
      return { ...s, shapes: s.shapes.map((m) => (m.id === a.id ? { ...m, mode: m.mode === "include" ? "exclude" : "include" } : m)) };
    case "setEnabled":
      return { ...s, enabled: a.enabled };
    case "setDrawMode":
      return { ...s, drawMode: a.mode };
    case "clear":
      return { ...s, shapes: [], selected: null, selectedIds: [] };
    case "load": {
      const shapes = a.shapes.map(asMask).filter((m): m is MaskShape => m !== null);
      return { ...s, shapes, nextId: shapes.reduce((n, m) => Math.max(n, m.id), 0) + 1, selected: null, selectedIds: [] };
    }
  }
}

/** 1 = pixel used, 0 = masked out; null when there are no shapes (the whole frame counts). */
export function maskPixels(shapes: readonly MaskShape[], w: number, h: number): Uint8Array | null {
  if (shapes.length === 0) return null;
  const includes = shapes.filter((m) => m.mode === "include");
  const used = new Uint8Array(w * h);
  if (includes.length === 0) used.fill(1);
  for (const m of includes) for (const i of roiPixels(m as unknown as Roi, w, h)) used[i] = 1;
  for (const m of shapes) if (m.mode === "exclude") for (const i of roiPixels(m as unknown as Roi, w, h)) used[i] = 0;
  return used;
}

/** Id of the topmost (last drawn) shape covering pixel (x, y), or null. */
export function maskAt(shapes: readonly MaskShape[], x: number, y: number, w: number, h: number): number | null {
  const i = y * w + x;
  for (let k = shapes.length - 1; k >= 0; k--) if (roiPixels(shapes[k] as unknown as Roi, w, h).includes(i)) return shapes[k].id;
  return null;
}

/** A copy of the °C field with masked-out pixels set to NaN (which autoScale already skips). */
export function maskField(c: Float32Array, used: Uint8Array): Float32Array {
  const out = new Float32Array(c.length);
  for (let i = 0; i < c.length; i++) out[i] = used[i] ? c[i] : NaN;
  return out;
}

/** min / max / mean over masked, valid (non-NaN) pixels; null when there are none. */
export function maskedStats(c: Float32Array, used: Uint8Array): { min: number; max: number; mean: number; n: number } | null {
  let min = Infinity, max = -Infinity, sum = 0, n = 0;
  for (let i = 0; i < c.length; i++) {
    const v = c[i];
    if (!used[i] || Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
    sum += v;
    n++;
  }
  return n ? { min, max, mean: sum / n, n } : null;
}

const keyFor = (scope: string) => `flir.masks.v1.${scope}`;

export function loadMasks(storage: Storage | null, scope = "live"): MaskState {
  try {
    const raw = storage?.getItem(keyFor(scope));
    if (!raw) return EMPTY_MASKS;
    const p = JSON.parse(raw) as { shapes?: unknown; enabled?: unknown; drawMode?: unknown };
    const s = maskReducer(EMPTY_MASKS, { type: "load", shapes: Array.isArray(p.shapes) ? p.shapes : [] });
    return { ...s, enabled: p.enabled !== false, drawMode: p.drawMode === "include" ? "include" : "exclude" };
  } catch {
    return EMPTY_MASKS;
  }
}

export function saveMasks(storage: Storage | null, s: MaskState, scope = "live"): void {
  try { storage?.setItem(keyFor(scope), JSON.stringify({ shapes: s.shapes, enabled: s.enabled, drawMode: s.drawMode })); } catch { /* ignore */ }
}

export function hasMasks(storage: Storage | null, scope: string): boolean {
  try { return storage?.getItem(keyFor(scope)) != null; } catch { return false; }
}
