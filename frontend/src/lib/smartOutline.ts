// Smart ROI outlines as closed paths, so the sample edge can be stroked solid and the ring edges
// dashed (a dash pattern needs a continuous path; per-pixel edge marks cannot carry one).
import { decodeLabels, type SmartOverlay } from "./smartLabels.ts";

/** A closed loop of pixel-corner points (x, y); the first point is not repeated at the end. */
export type Loop = [number, number][];

/**
 * Boundary loops of the region {1 ≤ label ≤ maxLabel} of a label crop, in crop pixel-corner
 * coordinates. maxLabel 1 is the sample edge; maxLabel i+2 is the outer edge of ring i — the same
 * boundaries `labelEdges` marks (out-of-crop neighbours count as unlabelled). Collinear runs are
 * merged into single segments.
 */
export function labelContours(labels: Uint8Array, w: number, h: number, maxLabel: number): Loop[] {
  const inside = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= w || y >= h) return false;
    const v = labels[y * w + x];
    return v >= 1 && v <= maxLabel;
  };
  const W = w + 1;
  // directed boundary edges, region on the right (clockwise on screen, y down): start -> ends
  const out = new Map<number, number[]>();
  const add = (x0: number, y0: number, x1: number, y1: number) => {
    const k = y0 * W + x0, list = out.get(k);
    if (list) list.push(y1 * W + x1); else out.set(k, [y1 * W + x1]);
  };
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!inside(x, y)) continue;
    if (!inside(x, y - 1)) add(x, y, x + 1, y);
    if (!inside(x + 1, y)) add(x + 1, y, x + 1, y + 1);
    if (!inside(x, y + 1)) add(x + 1, y + 1, x, y + 1);
    if (!inside(x - 1, y)) add(x, y + 1, x, y);
  }
  const loops: Loop[] = [];
  for (const start of [...out.keys()]) {
    while ((out.get(start)?.length ?? 0) > 0) {
      const pts: number[] = [start];
      let at = start;
      for (;;) {  // every vertex has as many edges in as out, so the walk returns to `start`
        const next = out.get(at)!.pop()!;
        if (next === start) break;
        pts.push(next);
        at = next;
      }
      loops.push(simplify(pts.map((k) => [k % W, Math.floor(k / W)] as [number, number])));
    }
  }
  return loops;
}

/** Drops points that sit on a straight line between their neighbours (closed loop). */
function simplify(pts: Loop): Loop {
  const n = pts.length;
  const keep = pts.filter((p, i) => {
    const a = pts[(i - 1 + n) % n], b = pts[(i + 1) % n];
    return (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0]) !== 0;
  });
  return keep.length >= 3 ? keep : pts;
}

/** Frame-coordinate outlines of one smart overlay: the sample edge and each ring's outer edge.
 *  Null when the overlay carries no outline (searching) or the crop does not decode. */
export function smartOutlines(o: SmartOverlay): { sample: Loop[]; rings: Loop[][] } | null {
  if (!o.labels || !o.bbox) return null;
  const [x0, y0, x1, y1] = o.bbox;
  const w = x1 - x0, h = y1 - y0;
  if (w <= 0 || h <= 0) return null;
  let labels: Uint8Array;
  try { labels = decodeLabels(o.labels, w, h); } catch { return null; }
  let top = 0;
  for (const v of labels) if (v > top) top = v;
  const shift = (loops: Loop[]) => loops.map((l) => l.map(([x, y]) => [x + x0, y + y0] as [number, number]));
  const rings: Loop[][] = [];
  for (let v = 2; v <= top; v++) rings.push(shift(labelContours(labels, w, h, v)));
  return { sample: shift(labelContours(labels, w, h, 1)), rings };
}

/** CSS colour tokens for a smart outline: rings dashed in --trace-3 and the sample edge in --live;
 *  both --muted when the stored outline is stale (the ROI changed since it was computed). */
export function smartOutlineTokens(stale: boolean): { rings: string; sample: string } {
  return stale ? { rings: "--muted", sample: "--muted" } : { rings: "--trace-3", sample: "--live" };
}
