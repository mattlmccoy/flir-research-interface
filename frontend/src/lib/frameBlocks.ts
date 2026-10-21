// Block fetching for playback: which blocks of frames (or smart ROI overlays) the playhead needs,
// and a loader that joins duplicate requests and aborts the ones nothing needs any more. Scrubbing
// used to queue every 37 MB block it passed (the browser allows 6 connections per host), so the
// small overlay requests waited behind downloads no one would look at.

/** Start of the block holding `index`. */
export function blockOf(index: number, size: number): number {
  return Math.floor(index / size) * size;
}

/** Blocks the playhead at `index` needs: its own, plus the next one once it is within `lead`
 *  frames of the end, so 1× playback never waits. Nothing past frame `n - 1`. */
export function wantedBlocks(index: number, n: number, size: number, lead: number): number[] {
  if (n <= 0) return [];
  const start = blockOf(index, size);
  const out = [start];
  if (index - start >= size - lead && start + size < n) out.push(start + size);
  return out;
}

/** True for the rejection of an aborted fetch (never a real failure: not cached, not retried). */
export function isAbort(e: unknown): boolean {
  return !!e && typeof e === "object" && (e as { name?: unknown }).name === "AbortError";
}

export interface BlockLoader {
  /** Fetch block `start` unless it is already running; resolves once `onData` has run. */
  ensure(start: number): Promise<void>;
  /** Abort every running fetch whose block is not in `keep`; returns the aborted starts. */
  retain(keep: readonly number[]): number[];
  abortAll(): void;
  /** Starts of the fetches still running. */
  inflight(): number[];
}

export function blockLoader<T>(fetch: (start: number, signal: AbortSignal) => Promise<T>, onData: (start: number, data: T) => void): BlockLoader {
  const running = new Map<number, { promise: Promise<void>; ctl: AbortController }>();
  const drop = (start: number): void => {
    const r = running.get(start);
    if (!r) return;
    running.delete(start);  // forget it now, so a new ensure starts a fresh fetch
    r.ctl.abort();
  };
  return {
    ensure(start) {
      const r = running.get(start);
      if (r) return r.promise;
      const ctl = new AbortController();
      const promise = fetch(start, ctl.signal)
        .then((data) => {
          if (ctl.signal.aborted) throw new DOMException("block fetch aborted", "AbortError");  // arrived after the abort
          onData(start, data);
        })
        .finally(() => { if (running.get(start)?.ctl === ctl) running.delete(start); });
      running.set(start, { promise, ctl });
      return promise;
    },
    retain(keep) {
      const gone = [...running.keys()].filter((s) => !keep.includes(s));
      for (const s of gone) drop(s);
      return gone;
    },
    abortAll() { for (const s of [...running.keys()]) drop(s); },
    inflight() { return [...running.keys()]; },
  };
}

/** Run the current `ensure` for frame `i`. If it is aborted because the store behind it was
 *  replaced meanwhile (a recompute bumps the overlay cache version and aborts the old store),
 *  retry against the new one, so a load never hangs on a silent abort. An abort from the store
 *  that is still current (the playhead moved on) is passed on. At most `swaps` retries. */
export async function ensureLatest(current: () => (i: number) => Promise<void>, i: number, swaps = 3): Promise<void> {
  let ensure = current();
  for (let k = 0; ; k++) {
    try {
      await ensure(i);
      return;
    } catch (e) {
      if (!isAbort(e) || k >= swaps) throw e;
      const now = current();
      if (now === ensure) throw e;
      ensure = now;
    }
  }
}

/** The error text a failed frame load may show, or null: an abort, or a load for a frame the
 *  playhead has left (`alive` false), is never this frame's error. */
export function loadFailure(e: unknown, alive: boolean): string | null {
  return !alive || isAbort(e) ? null : String(e);
}
