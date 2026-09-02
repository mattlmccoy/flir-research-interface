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

/** Topmost ROI under (x, y): spots within `tol` pixels win over rectangles; later ROIs win ties. */
export function hitTest(rois: Roi[], x: number, y: number, tol: number): number | null {
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.kind === "spot" && Math.abs(r.x - x) <= tol && Math.abs(r.y - y) <= tol) return r.id;
  }
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.kind === "rect" && x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1) return r.id;
  }
  return null;
}

/** Trace colours as CSS variables from theme.css; the first trace is phosphor green (spec §2). */
export const TRACE_TOKENS = ["--live", "--accent", "--trace-3", "--trace-4", "--trace-5", "--trace-6"] as const;

export function traceColor(i: number): string {
  return `var(${TRACE_TOKENS[((i % TRACE_TOKENS.length) + TRACE_TOKENS.length) % TRACE_TOKENS.length]})`;
}
