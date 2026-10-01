import { roiReducer, type Roi, type RoiAction, type RoiState } from "./roi.ts";

/**
 * Undo/redo around `roiReducer`. Only edits that change the ROIs themselves are undoable;
 * selection changes ride along but never make a step of their own. A drag or a typed name/optic
 * dispatches many small actions, so consecutive actions of the same kind on the same ROI(s)
 * collapse into one step until a `commit` (pointer up) or a different action ends the gesture.
 */
export interface RoiHistory { past: RoiState[]; present: RoiState; future: RoiState[]; gesture: string | null; }
export type RoiHistoryAction =
  | RoiAction
  | { type: "undo" }
  | { type: "redo" }
  /** Replace the ROIs and forget the history (opening another run, switching scope). */
  | { type: "load"; rois: Roi[] };

export const HISTORY_LIMIT = 100;

export function initHistory(present: RoiState): RoiHistory {
  return { past: [], present, future: [], gesture: null };
}

/** The coalescing key of a continuous edit; null for actions that are always their own step. */
function gestureKey(a: RoiAction): string | null {
  switch (a.type) {
    case "move": case "rename": case "recolor": case "setOptics": return `${a.type}:${a.id}`;
    case "moveMany": return `moveMany:${a.ids.join(",")}`;
    case "setVertex": return `setVertex:${a.id}:${a.index}`;
    case "setEndpoint": return `setEndpoint:${a.id}:${a.end}`;
    case "remove": return "remove";  // Delete on a multi-selection is one step (bracketed by commits)
    default: return null;
  }
}

export function roiHistoryReducer(h: RoiHistory, a: RoiHistoryAction): RoiHistory {
  switch (a.type) {
    case "undo": {
      const prev = h.past[h.past.length - 1];
      if (!prev) return h;
      // ids are never reused, so an undone add can't hand its id to the next new ROI
      const present = { ...prev, nextId: Math.max(prev.nextId, h.present.nextId) };
      return { past: h.past.slice(0, -1), present, future: [h.present, ...h.future], gesture: null };
    }
    case "redo": {
      const next = h.future[0];
      if (!next) return h;
      const present = { ...next, nextId: Math.max(next.nextId, h.present.nextId) };
      return { past: [...h.past, h.present], present, future: h.future.slice(1), gesture: null };
    }
    case "load":
      return initHistory(roiReducer(h.present, { type: "replace", rois: a.rois }));
    case "commit":
      return h.gesture === null ? h : { ...h, gesture: null };
  }
  const present = roiReducer(h.present, a);
  if (present === h.present) return h;
  if (present.rois === h.present.rois || (present.rois.length === 0 && h.present.rois.length === 0)) {
    return { ...h, present };  // selection only, or clearing nothing
  }
  const key = gestureKey(a);
  if (key !== null && key === h.gesture) return { ...h, present };  // same drag / same field
  const past = [...h.past, h.present].slice(-HISTORY_LIMIT);
  return { past, present, future: [], gesture: key };
}
