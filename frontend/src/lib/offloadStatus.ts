// Auto-offload queue (GET /api/storage/offload) in plain words for Setup → Storage.
// States come from backend offload.decide() plus "moving" from the sweep in offload_routes.py.

export interface OffloadEntry {
  collection: string;
  name: string;
  queued: number;
  attempts: number;
  last_try: number | null;
  error: string | null;
  state: string;
}
export interface OffloadDoc { enabled: boolean; drive_connected: boolean; pending: OffloadEntry[]; }
export type Tone = "busy" | "wait" | "bad";

const needsAttention = (e: OffloadEntry): boolean => e.state === "stuck" || e.state === "clash";

export function offloadRow(e: OffloadEntry): { label: string; tone: Tone } {
  if (e.state === "moving") return { label: "moving to the SSD…", tone: "busy" };
  if (e.state === "move") return { label: "ready to move", tone: "busy" };
  if (e.state === "stuck") {
    return { label: `gave up after ${e.attempts} tries: ${e.error ?? "unknown error"} (the run is safe on this Mac)`, tone: "bad" };
  }
  if (e.state === "clash") {
    return { label: "a run with this name is already on the SSD; both kept, move it by hand", tone: "bad" };
  }
  if (e.state.startsWith("wait:")) {
    const why = e.state.slice(5);
    const failed = e.attempts > 0 && e.error ? ` (try ${e.attempts} failed: ${e.error})` : "";
    return { label: `waiting: ${why}${failed}`, tone: "wait" };
  }
  return { label: e.state, tone: "wait" };
}

export function offloadHeadline(d: OffloadDoc | null): string {
  if (!d) return "status unavailable";
  if (!d.enabled) return "off: finished runs stay on this Mac";
  const n = d.pending.length;
  if (n === 0) return "on: nothing waiting";
  const bad = d.pending.filter(needsAttention).length;
  const head = `on: ${n} run${n === 1 ? "" : "s"} waiting`;
  return bad ? `${head}, ${bad} need${bad === 1 ? "s" : ""} attention` : head;
}
