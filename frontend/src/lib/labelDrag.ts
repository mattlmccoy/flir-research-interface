/**
 * Draggable ROI-label offsets: a per-ROI (dx, dy) nudge from a label's automatic anchor, so the
 * user can move a chip off the part of the thermal image it obscures. Offsets persist per ROI
 * scope (live vs a specific experiment) in localStorage, like the ROIs themselves.
 */

export interface Offset { dx: number; dy: number; }
export type Offsets = Record<number, Offset>;

export interface ChipRect { id: number; x: number; y: number; w: number; h: number; }

const KEY_PREFIX = "fri.roilabels.v1";

export function offsetsKey(scope = "live"): string {
  return `${KEY_PREFIX}.${scope}`;
}

/** Topmost chip whose rectangle contains (x, y), or null. Later entries are drawn on top. */
export function hitChip(rects: ChipRect[], x: number, y: number): number | null {
  for (let i = rects.length - 1; i >= 0; i--) {
    const r = rects[i];
    if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return r.id;
  }
  return null;
}

export function loadOffsets(storage: Storage | null, scope = "live"): Offsets {
  if (!storage) return {};
  try {
    const raw = storage.getItem(offsetsKey(scope));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, Offset>;
    const out: Offsets = {};
    for (const [id, o] of Object.entries(parsed)) {
      if (o && Number.isFinite(o.dx) && Number.isFinite(o.dy)) out[Number(id)] = { dx: o.dx, dy: o.dy };
    }
    return out;
  } catch {
    return {};
  }
}

export function saveOffsets(storage: Storage | null, scope: string, offsets: Offsets): void {
  if (!storage) return;
  try {
    const keys = Object.keys(offsets);
    if (keys.length === 0) storage.removeItem(offsetsKey(scope));
    else storage.setItem(offsetsKey(scope), JSON.stringify(offsets));
  } catch {
    /* storage unavailable — offsets stay in-memory only */
  }
}
