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
    if (r.kind === "polyline") {
      for (let k = 1; k < r.points.length; k++) {
        const [ax, ay] = r.points[k - 1], [bx, by] = r.points[k];
        if (segmentDistance(x, y, ax, ay, bx, by) <= tol) return r.id;
      }
    }
  }
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.kind === "rect" && x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1) return r.id;
    if (r.kind === "circle" && Math.hypot(x - r.cx, y - r.cy) <= r.r) return r.id;
  }
  return null;
}

/** Trace colours as CSS variables from theme.css; the first trace is phosphor green (spec §2). */
export const TRACE_TOKENS = ["--live", "--accent", "--trace-3", "--trace-4", "--trace-5", "--trace-6"] as const;

export function traceColor(i: number): string {
  return `var(${TRACE_TOKENS[((i % TRACE_TOKENS.length) + TRACE_TOKENS.length) % TRACE_TOKENS.length]})`;
}
