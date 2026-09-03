/** ROI delta traces (A − B) and the record-time keyboard marks. Pure; shared by live and playback. */
import { nearestIndex } from "./events.ts";
import type { Trace } from "../components/TimePlot.tsx";

export const DELTA_ID = -1;

/** A − B on A's time axis; B is sampled at the nearest time. Virtual id DELTA_ID. */
export function deltaTrace(a: Trace, b: Trace): Trace {
  const t = Array.from(a.t), v: number[] = [];
  for (let i = 0; i < t.length; i++) {
    if (b.t.length === 0) { v.push(NaN); continue; }
    const j = nearestIndex(b.t, t[i]);
    v.push(a.v[i] - b.v[j]);
  }
  return { id: DELTA_ID, label: `${a.label} − ${b.label}`, color: "#ffffff", t, v };
}

export interface MarkDef { label: string; key?: string; }
/** Keyboard marks while recording, from the project profile; never while typing in a field. */
export function markForKey(key: string, inInput: boolean, marks: MarkDef[]): string | null {
  if (inInput || key.length !== 1) return null;
  const k = key.toLowerCase();
  return marks.find((m) => m.key && m.key.toLowerCase() === k)?.label ?? null;
}
