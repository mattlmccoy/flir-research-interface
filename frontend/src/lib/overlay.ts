/** Pure geometry for the ROI overlay: client→image mapping, hit testing, trace colours. */
import type { Roi } from "./roi.ts";

export interface Box { left: number; top: number; width: number; height: number; }

/** Maps a client point onto integer image pixels, clamped to [0, w-1] × [0, h-1]. */
export function clientToImage(box: Box, clientX: number, clientY: number, w: number, h: number): { x: number; y: number } {
  const fx = box.width > 0 ? (clientX - box.left) / box.width : 0;
  const fy = box.height > 0 ? (clientY - box.top) / box.height : 0;
  const x = Math.min(w - 1, Math.max(0, Math.floor(fx * w)));
  const y = Math.min(h - 1, Math.max(0, Math.floor(fy * h)));
  return { x, y };
}

/** Distance from (px,py) to the segment (ax,ay)-(bx,by). */
export function segmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const vx = bx - ax, vy = by - ay;
  const len2 = vx * vx + vy * vy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * vx + (py - ay) * vy) / len2));
  const qx = ax + t * vx, qy = ay + t * vy;
  return Math.hypot(px - qx, py - qy);
}

/**
 * Topmost ROI under (x, y). Thin shapes (spots, lines, polylines within `tol`) win over filled
 * ones (rectangles, circles) so a small mark inside a big region stays selectable; later ROIs win ties.
 */
export function hitTest(rois: Roi[], x: number, y: number, tol: number): number | null {
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.kind === "spot" && Math.abs(r.x - x) <= tol && Math.abs(r.y - y) <= tol) return r.id;
    if (r.kind === "line" && segmentDistance(x, y, r.x0, r.y0, r.x1, r.y1) <= tol) return r.id;
    if (r.kind === "polyline" && r.points.some((p, i) => i > 0 && segmentDistance(x, y, r.points[i - 1][0], r.points[i - 1][1], p[0], p[1]) <= tol)) return r.id;
  }
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.kind === "rect" && x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1) return r.id;
    if (r.kind === "circle" && Math.hypot(x - r.cx, y - r.cy) <= r.r) return r.id;
    if (r.kind === "ellipse" && ((x - r.cx) / r.rx) ** 2 + ((y - r.cy) / r.ry) ** 2 <= 1) return r.id;
    if (r.kind === "polygon" && pointInPolygon(x, y, r.points)) return r.id;
  }
  return null;
}

export function pointInPolygon(x: number, y: number, pts: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Nine preset ROI colours (phosphor, amber, sky, pink, lime, violet, white, coral, cyan). */
export const COLOR_PRESETS = ["#5cff8a", "#ffb454", "#6ec3ff", "#ff8ad8", "#c9d64f", "#b48cff", "#f5f7fa", "#ff5f56", "#3ee6d6"] as const;

/** The ROI's own colour when set, else its trace token by index. */
export function roiColor(roi: Roi, index: number): string {
  return roi.color ?? traceColor(index);
}

/** Trace colours as CSS variables from theme.css; the first trace is phosphor green (spec §2). */
export const TRACE_TOKENS = ["--live", "--accent", "--trace-3", "--trace-4", "--trace-5", "--trace-6"] as const;

export function traceColor(i: number): string {
  return `var(${TRACE_TOKENS[((i % TRACE_TOKENS.length) + TRACE_TOKENS.length) % TRACE_TOKENS.length]})`;
}

export type VertexHit = { kind: "vertex"; index: number } | { kind: "endpoint"; end: 0 | 1 };

/** A polygon/polyline vertex or line endpoint within `tol` image-pixels of (x, y), or null. */
export function vertexHit(roi: Roi, x: number, y: number, tol: number): VertexHit | null {
  const near = (vx: number, vy: number) => Math.abs(vx - x) <= tol && Math.abs(vy - y) <= tol;
  if (roi.kind === "polygon" || roi.kind === "polyline") {
    for (let i = 0; i < roi.points.length; i++) if (near(roi.points[i][0], roi.points[i][1])) return { kind: "vertex", index: i };
    return null;
  }
  if (roi.kind === "line") {
    if (near(roi.x0, roi.y0)) return { kind: "endpoint", end: 0 };
    if (near(roi.x1, roi.y1)) return { kind: "endpoint", end: 1 };
  }
  return null;
}

/** Vertex/endpoint image-space points of an editable ROI, for drawing drag handles. */
export function vertexHandles(roi: Roi): [number, number][] {
  if (roi.kind === "polygon" || roi.kind === "polyline") return roi.points.map((p) => [p[0], p[1]]);
  if (roi.kind === "line") return [[roi.x0, roi.y0], [roi.x1, roi.y1]];
  return [];
}

/** A ROI's centre and a "reach" radius in canvas pixels (image coords × sx/sy), so a leader line
 *  can tie to the shape itself — the ring edge facing the label for circles/ellipses, the centre
 *  (reach 0) otherwise — instead of floating at the label's bounding-box corner. */
export function roiLeaderAnchor(r: Roi, sx: number, sy: number): [number, number, number] {
  switch (r.kind) {
    case "spot": return [(r.x + 0.5) * sx, (r.y + 0.5) * sy, 0];
    case "rect": return [(r.x0 + r.x1) / 2 * sx, (r.y0 + r.y1) / 2 * sy, 0];
    case "circle": return [(r.cx + 0.5) * sx, (r.cy + 0.5) * sy, r.r * sx];
    case "ellipse": return [(r.cx + 0.5) * sx, (r.cy + 0.5) * sy, Math.min(r.rx * sx, r.ry * sy)];
    case "line": return [((r.x0 + r.x1) / 2 + 0.5) * sx, ((r.y0 + r.y1) / 2 + 0.5) * sy, 0];
    default: {  // polyline / polygon: centroid of the vertices
      const pts = r.points;
      const mx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
      const my = pts.reduce((a, p) => a + p[1], 0) / pts.length;
      return [(mx + 0.5) * sx, (my + 0.5) * sy, 0];
    }
  }
}
