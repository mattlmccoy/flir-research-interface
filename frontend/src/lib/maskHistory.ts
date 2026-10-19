import { maskReducer, type MaskAction, type MaskState } from "./mask.ts";

/**
 * Undo/redo around `maskReducer`, mirroring the ROI history: only changes to the regions are
 * undoable (selection, on/off and the include/exclude choice ride along), and a drag (many small
 * edits of the same kind on the same region) is one step until a `commit` ends the gesture.
 */
export interface MaskHistory { past: MaskState[]; present: MaskState; future: MaskState[]; gesture: string | null; }
export type MaskHistoryAction = MaskAction | { type: "undo" } | { type: "redo" };

export const MASK_HISTORY_LIMIT = 100;

export function initMaskHistory(present: MaskState): MaskHistory {
  return { past: [], present, future: [], gesture: null };
}

function gestureKey(a: MaskAction): string | null {
  if (a.type !== "edit") return null;
  const e = a.action;
  switch (e.type) {
    case "move": return `move:${e.id}`;
    case "moveMany": return `moveMany:${e.ids.join(",")}`;
    case "setVertex": return `setVertex:${e.id}:${e.index}`;
    case "remove": return "remove";  // Delete on a multi-selection is one step (bracketed by commits)
    default: return null;
  }
}

export function maskHistoryReducer(h: MaskHistory, a: MaskHistoryAction): MaskHistory {
  switch (a.type) {
    case "undo": {
      const prev = h.past[h.past.length - 1];
      if (!prev) return h;
      // ids are never reused, and the on/off and draw-mode choices are not part of the history
      const present = { ...prev, nextId: Math.max(prev.nextId, h.present.nextId), enabled: h.present.enabled, drawMode: h.present.drawMode };
      return { past: h.past.slice(0, -1), present, future: [h.present, ...h.future], gesture: null };
    }
    case "redo": {
      const next = h.future[0];
      if (!next) return h;
      const present = { ...next, nextId: Math.max(next.nextId, h.present.nextId), enabled: h.present.enabled, drawMode: h.present.drawMode };
      return { past: [...h.past, h.present], present, future: h.future.slice(1), gesture: null };
    }
    case "load":
      return initMaskHistory(maskReducer(h.present, a));
  }
  if (a.type === "edit" && a.action.type === "commit") return h.gesture === null ? h : { ...h, gesture: null };
  const present = maskReducer(h.present, a);
  if (present === h.present) return h;
  if (present.shapes === h.present.shapes || (present.shapes.length === 0 && h.present.shapes.length === 0)) {
    return { ...h, present };  // selection / on-off / draw mode only
  }
  const key = gestureKey(a);
  if (key !== null && key === h.gesture) return { ...h, present };
  const past = [...h.past, h.present].slice(-MASK_HISTORY_LIMIT);
  return { past, present, future: [], gesture: key };
}
