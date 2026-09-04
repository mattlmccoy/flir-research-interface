/** Collision-resolving placement for ROI labels so nearby ones don't overlap. */

export interface LabelBox { id: number; ax: number; ay: number; w: number; h: number; }
export interface Placed { id: number; x: number; y: number; ax: number; ay: number; displaced: boolean; }

interface Rect { x: number; y: number; w: number; h: number; }

const xOverlap = (a: Rect, b: Rect): boolean => a.x < b.x + b.w && b.x < a.x + a.w;

/**
 * Places labels near their anchors without overlapping. Items are processed in the order given —
 * put higher-priority labels (e.g. the selected ROI) first so they keep their anchor and the rest
 * flow around them. A label that must move to avoid a collision is flagged `displaced` so the
 * caller can draw a leader line back to its anchor. Everything stays inside `box`.
 */
export function layoutLabels(
  items: LabelBox[],
  box: { width: number; height: number },
  gap = 2,
): Placed[] {
  const placed: Rect[] = [];
  const out: Placed[] = [];
  for (const it of items) {
    const x = Math.min(Math.max(0, it.ax), Math.max(0, box.width - it.w));
    const y = resolveY(x, it.ay, it.w, it.h, placed, box, gap);
    placed.push({ x, y, w: it.w, h: it.h });
    out.push({ id: it.id, x, y, ax: it.ax, ay: it.ay, displaced: Math.abs(y - it.ay) > 0.5 });
  }
  return out;
}

function resolveY(
  x: number, ay: number, w: number, h: number, placed: Rect[], box: { width: number; height: number }, gap: number,
): number {
  const maxY = Math.max(0, box.height - h);
  const start = Math.min(Math.max(0, ay), maxY);
  const rel = placed.filter((r) => xOverlap({ x, y: 0, w, h }, r)); // only labels sharing a column matter

  const sweep = (dir: 1 | -1): number => {
    let y = start;
    for (let guard = 0; guard <= rel.length; guard++) {
      const hit = rel.find((r) => y < r.y + r.h + gap && r.y < y + h + gap);
      if (!hit) return y;
      y = dir === 1 ? r_below(hit, gap) : r_above(hit, h, gap);
      if (y < 0 || y > maxY) break;
    }
    return y;
  };

  const down = sweep(1);
  if (down >= 0 && down <= maxY) return down;
  const up = sweep(-1);
  if (up >= 0 && up <= maxY) return up;
  return start; // nowhere clear — sit at the anchor and accept the overlap
}

const r_below = (r: Rect, gap: number): number => r.y + r.h + gap;
const r_above = (r: Rect, h: number, gap: number): number => r.y - h - gap;
