import { roiReducer, type Roi, type RoiAction, type RoiState } from "./roi.ts";

/** Undo/redo stacks of ROI lists around the plain ROI state. Only the shapes are snapshotted:
 *  selection is view state, and nextId never goes back so an id is never reused. */
export interface RoiHistory { past: Roi[][]; present: RoiState; future: Roi[][]; group: string | null; }
export type RoiHistoryAction = RoiAction | { type: "undo" } | { type: "redo" };

const LIMIT = 100;

export const initRoiHistory = (present: RoiState): RoiHistory => ({ past: [], present, future: [], group: null });

/** Drag actions sharing a key coalesce into one undo step until a "commit" (pointer up) or any
 *  other action; null means the action changes no shapes and is not an undo step. */
function stepKey(a: RoiAction): string | null {
  switch (a.type) {
    case "move": return `move:${a.id}`;
    case "moveMany": return `moveMany:${a.ids.join(",")}`;
    case "setVertex": return `vertex:${a.id}:${a.index}`;
    case "setEndpoint": return `end:${a.id}:${a.end}`;
    case "select": case "toggleSelect": case "commit": case "replace": return null;
    default: return "";
  }
}

function restore(s: RoiState, rois: Roi[]): RoiState {
  const ids = new Set(rois.map((r) => r.id));
  const selectedIds = s.selectedIds.filter((id) => ids.has(id));
  const selected = s.selected !== null && ids.has(s.selected) ? s.selected : (selectedIds[selectedIds.length - 1] ?? null);
  return { ...s, rois, selected, selectedIds };
}

export function roiHistoryReducer(h: RoiHistory, a: RoiHistoryAction): RoiHistory {
  if (a.type === "undo") {
    const prev = h.past[h.past.length - 1];
    if (!prev) return h;
    return { past: h.past.slice(0, -1), present: restore(h.present, prev), future: [h.present.rois, ...h.future], group: null };
  }
  if (a.type === "redo") {
    const next = h.future[0];
    if (!next) return h;
    return { past: [...h.past, h.present.rois], present: restore(h.present, next), future: h.future.slice(1), group: null };
  }
  const present = roiReducer(h.present, a);
  if (a.type === "replace") return initRoiHistory(present);
  const key = stepKey(a);
  if (key === null || present.rois === h.present.rois) return { ...h, present, group: a.type === "commit" ? null : h.group };
  if (key !== "" && key === h.group) return { ...h, present, future: [] };
  return { past: [...h.past, h.present.rois].slice(-LIMIT), present, future: [], group: key || null };
}

/** The history command for a keydown: cmd/ctrl+Z undoes; cmd/ctrl+Y or shift+cmd/ctrl+Z redoes. */
export function undoKeyFor(e: { key: string; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }): "undo" | "redo" | null {
  if (!(e.metaKey || e.ctrlKey) || e.altKey) return null;
  const k = e.key.toLowerCase();
  if (k === "z") return e.shiftKey ? "redo" : "undo";
  if (k === "y") return "redo";
  return null;
}
