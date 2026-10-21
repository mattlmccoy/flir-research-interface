// Saving a recorded run's visible adjustment (its sidecar): the debounced, in-order writer behind
// useRunVisibleAdjust and the save status it reports. No React here, so it is tested directly.
import type { VisibleAdjust } from "./visibleAdjust.ts";
import type { AdjustSource } from "./visibleAdjustUi.ts";

/** What a write does: a slider save (PUT) or a reset (DELETE of the sidecar). */
export type SaveOp = "save" | "reset";
/** The save status, tagged with the run it is about, so one run's failure never shows on another. */
export type SaveState =
  | { state: "idle" }
  | { state: "saving"; name: string; op: SaveOp }
  | { state: "error"; name: string; op: SaveOp; error: string };
/** `start` begins write `n` (a debounced save starts when the slider moves); `done` / `fail` end it;
 *  `clear` forgets the status (a new run is shown). */
export type SaveAction =
  | { type: "start"; n: number; name: string; op: SaveOp }
  | { type: "done"; n: number }
  | { type: "fail"; n: number; error: string }
  | { type: "clear" };
/** The status and the number of the latest write; an older write's outcome is ignored. */
export interface SaveTrack { n: number; save: SaveState }

export function saveReducer(s: SaveTrack, a: SaveAction): SaveTrack {
  switch (a.type) {
    case "start": return { n: a.n, save: { state: "saving", name: a.name, op: a.op } };
    case "done": return a.n === s.n ? { n: s.n, save: { state: "idle" } } : s;
    case "fail":
      if (a.n !== s.n || s.save.state === "idle") return s;
      return { n: s.n, save: { state: "error", name: s.save.name, op: s.save.op, error: a.error } };
    case "clear": return { n: s.n, save: { state: "idle" } };
  }
}

/** The status as run `name` should show it: another run's saving or error reads as idle. */
export function saveStateFor(s: SaveState, name: string): SaveState {
  return s.state === "idle" || s.name === name ? s : { state: "idle" };
}

/** Whether "reset to as-recorded" can be pressed: the run has a sidecar, or the last reset failed
 *  (the sidecar may still be there, so the reset must stay retryable). */
export function canReset(source: AdjustSource, s: SaveState): boolean {
  return source === "sidecar" || (s.state === "error" && s.op === "reset");
}

export interface WriterDeps {
  write: (name: string, a: VisibleAdjust) => Promise<unknown>;
  clear: (name: string) => Promise<unknown>;
  onAction: (a: SaveAction) => void;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (id: unknown) => void;
  debounceMs: number;
}

/** Debounced, in-order sidecar writes. `set` saves after `debounceMs` (a newer move replaces the
 *  pending one); `reset` drops a pending save and deletes the sidecar; `flush` sends a pending save
 *  now and resolves once every write so far has settled (it never rejects: failures are reported
 *  through `onAction`), e.g. before a regenerate reads the sidecar. */
export function createAdjustWriter(d: WriterDeps) {
  let chain: Promise<unknown> = Promise.resolve();
  let n = 0;
  let pending: { name: string; adjust: VisibleAdjust; timer: unknown } | null = null;
  function enqueue(name: string, op: SaveOp, run: () => Promise<unknown>): void {
    const k = ++n;
    d.onAction({ type: "start", n: k, name, op });
    chain = chain.catch(() => undefined).then(run).then(
      () => d.onAction({ type: "done", n: k }),
      (e: unknown) => d.onAction({ type: "fail", n: k, error: String(e) }),
    );
  }
  function sendPending(): void {
    const p = pending;
    if (!p) return;
    d.clearTimer(p.timer);
    pending = null;
    enqueue(p.name, "save", () => d.write(p.name, p.adjust));
  }
  return {
    set(name: string, adjust: VisibleAdjust): void {
      if (pending) d.clearTimer(pending.timer);
      d.onAction({ type: "start", n: ++n, name, op: "save" });
      pending = { name, adjust, timer: d.setTimer(sendPending, d.debounceMs) };
    },
    reset(name: string): void {
      if (pending) { d.clearTimer(pending.timer); pending = null; }
      enqueue(name, "reset", () => d.clear(name));
    },
    flush(): Promise<void> {
      sendPending();
      return chain.then(() => undefined, () => undefined);
    },
  };
}
