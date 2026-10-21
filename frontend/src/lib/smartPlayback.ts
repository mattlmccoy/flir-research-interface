// Recorded-run smart ROI outlines: the stored per-frame overlays (GET …/smart-roi/{id}/overlay),
// fetched a block of frames at a time and cached (useSmartPlaybackOverlays.ts); pure helpers here.
import type { SmartOverlay } from "./smartLabels.ts";
import { isNotFound } from "./smartSeries.ts";
import { blockLoader, isAbort, type BlockLoader } from "./frameBlocks.ts";

/** Key `${roiId}:${blockStart}` → that block's overlays, or "missing" (no stored series / failed). */
export type OverlayCache = Map<string, SmartOverlay[] | "missing">;

export const OVERLAY_BLOCK = 120;

export function overlayBlock(index: number, size: number): number {
  return Math.floor(index / size) * size;
}

/** The overlay of each ROI at frame `index` that is already cached (absent ones are skipped). */
export function pickOverlays(cache: OverlayCache, ids: number[], index: number, size: number): SmartOverlay[] {
  const start = overlayBlock(index, size);
  const out: SmartOverlay[] = [];
  for (const id of ids) {
    const block = cache.get(`${id}:${start}`);
    const o = Array.isArray(block) ? block[index - start] : undefined;
    if (o) out.push(o);
  }
  return out;
}

/** A failed block fetch: a 404 means the series is not computed (cache "missing" until the cache
 *  version is bumped); anything else (operator unreachable, 5xx) is retried, never cached. */
export function overlayOnError(e: unknown): "missing" | "retry" {
  return isNotFound(e) ? "missing" : "retry";
}

/** Index of the frame on screen (`frame.header.index`), or null when none is shown. The outline
 *  and the readout follow this, not the playhead, so they can never sit over another frame. */
export function shownIndex(frame: { header: object } | null): number | null {
  const i = (frame?.header as { index?: unknown } | undefined)?.index;
  return typeof i === "number" && Number.isInteger(i) ? i : null;
}

export interface OverlayStore {
  readonly cache: OverlayCache;
  /** Resolves once every id's overlay block for frame `index` is cached, known missing, or failed
   *  transiently (`onRetry` is called; the frame is not held back). Rejects only when aborted. */
  ensure(ids: readonly number[], index: number): Promise<void>;
  /** Abort overlay fetches whose block holds none of the frames in `indexes`. */
  retain(indexes: readonly number[]): void;
  abortAll(): void;
  pick(ids: number[], index: number): SmartOverlay[];
}

export function overlayStore(
  fetch: (id: number, start: number, signal: AbortSignal) => Promise<SmartOverlay[]>,
  size: number,
  hooks: { onChange: () => void; onRetry: () => void },
): OverlayStore {
  const cache: OverlayCache = new Map();
  const loaders = new Map<number, BlockLoader>();
  const loader = (id: number): BlockLoader => {
    let l = loaders.get(id);
    if (!l) {
      l = blockLoader((start, signal) => fetch(id, start, signal), (start, list: SmartOverlay[]) => { cache.set(`${id}:${start}`, list); });
      loaders.set(id, l);
    }
    return l;
  };
  const one = (id: number, start: number): Promise<void> => {
    if (cache.has(`${id}:${start}`)) return Promise.resolve();
    return loader(id).ensure(start).then(
      () => { hooks.onChange(); },
      (e: unknown) => {
        if (isAbort(e)) throw e;  // nothing needs it any more: not cached, not retried
        if (overlayOnError(e) === "missing") cache.set(`${id}:${start}`, "missing");  // not computed yet
        else hooks.onRetry();
        hooks.onChange();
      },
    );
  };
  return {
    cache,
    ensure(ids, index) {
      const start = overlayBlock(index, size);
      return Promise.all(ids.map((id) => one(id, start))).then(() => undefined);
    },
    retain(indexes) {
      const keep = [...new Set(indexes.map((i) => overlayBlock(i, size)))];
      for (const l of loaders.values()) l.retain(keep);
    },
    abortAll() { for (const l of loaders.values()) l.abortAll(); },
    pick(ids, index) { return pickOverlays(cache, ids, index, size); },
  };
}
