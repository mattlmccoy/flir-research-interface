/**
 * Visible ↔ IR alignment calibration: point pairs picked on both images (normalised 0..1),
 * a fitted homography, and its residual. Persisted per browser; also uploaded to the operator so
 * recordings can carry it (see api.alignment*).
 */
import { fitHomography, rmsResidual, type H3, type Pt } from "./homography.ts";

export interface Pair { ir: Pt; visible: Pt; }
export interface AlignmentState {
  pairs: Pair[];
  /** A half-finished pair: whichever side was clicked first. */
  pending: { ir?: Pt; visible?: Pt } | null;
  /** Homography mapping visible (normalised) → IR (normalised), null until solved. */
  H: H3 | null;
  /** RMS reprojection error of the solved fit in IR pixels. */
  rmsPx: number | null;
  note: string;
}
export const EMPTY_ALIGNMENT: AlignmentState = Object.freeze({ pairs: [], pending: null, H: null, rmsPx: null, note: "" }) as AlignmentState;

export type AlignmentAction =
  | { type: "pick"; side: "ir" | "visible"; p: Pt }
  | { type: "removePair"; index: number }
  | { type: "solve"; irSize: [number, number] }
  | { type: "note"; note: string }
  | { type: "adopt"; state: AlignmentState }
  | { type: "clear" };

export function alignmentReducer(s: AlignmentState, a: AlignmentAction): AlignmentState {
  switch (a.type) {
    case "pick": {
      const pending = { ...(s.pending ?? {}), [a.side]: a.p };
      if (pending.ir && pending.visible) {
        return { ...s, pairs: [...s.pairs, { ir: pending.ir, visible: pending.visible }], pending: null, H: null, rmsPx: null };
      }
      return { ...s, pending, H: null, rmsPx: null };
    }
    case "removePair":
      return { ...s, pairs: s.pairs.filter((_, i) => i !== a.index), H: null, rmsPx: null };
    case "solve": {
      const src = s.pairs.map((p) => p.visible), dst = s.pairs.map((p) => p.ir);
      const H = fitHomography(src, dst);
      if (!H) return { ...s, H: null, rmsPx: null };
      const [w, h] = a.irSize;
      // residual in normalised units → pixels (use the geometric mean of the axes' scales)
      const rms = rmsResidual(H, src, dst) * Math.sqrt(w * h);
      return { ...s, H, rmsPx: rms };
    }
    case "note":
      return { ...s, note: a.note.slice(0, 120) };
    case "adopt":
      return { ...a.state, pending: null };
    case "clear":
      return EMPTY_ALIGNMENT;
  }
}

const KEY = "fri.alignment.v1";
const isPt = (v: unknown): v is Pt => Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "number" && Number.isFinite(x));
const isH = (v: unknown): v is H3 => Array.isArray(v) && v.length === 3 && v.every((r) => Array.isArray(r) && r.length === 3 && r.every((x) => typeof x === "number" && Number.isFinite(x)));

export function serializeAlignment(s: AlignmentState): { pairs: Pair[]; H: H3 | null; rmsPx: number | null; note: string } {
  return { pairs: s.pairs, H: s.H, rmsPx: s.rmsPx, note: s.note };
}

export function parseAlignment(v: unknown): AlignmentState {
  if (!v || typeof v !== "object") return EMPTY_ALIGNMENT;
  const r = v as Record<string, unknown>;
  if (!Array.isArray(r.pairs)) return EMPTY_ALIGNMENT;
  const pairs: Pair[] = [];
  for (const p of r.pairs) {
    const q = p as Record<string, unknown>;
    if (q && isPt(q.ir) && isPt(q.visible)) pairs.push({ ir: q.ir, visible: q.visible });
  }
  return {
    pairs,
    pending: null,
    H: isH(r.H) ? r.H : null,
    rmsPx: typeof r.rmsPx === "number" && Number.isFinite(r.rmsPx) ? r.rmsPx : null,
    note: typeof r.note === "string" ? r.note.slice(0, 120) : "",
  };
}

export function loadAlignment(storage: Storage | null): AlignmentState {
  try {
    const raw = storage?.getItem(KEY);
    return raw ? parseAlignment(JSON.parse(raw)) : EMPTY_ALIGNMENT;
  } catch {
    return EMPTY_ALIGNMENT;
  }
}

export function saveAlignment(storage: Storage | null, s: AlignmentState): void {
  try { storage?.setItem(KEY, JSON.stringify(serializeAlignment(s))); } catch { /* ignore */ }
}
