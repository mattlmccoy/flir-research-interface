// Fetches and caches a recorded run's stored smart ROI outlines, a block of frames at a time
// (GET /api/experiments/{name}/smart-roi/{id}/overlay); the pure store is smartPlayback.ts
// overlayStore. PlaybackPage awaits `ensure` before it shows a frame, so a frame and its outline
// appear together, and calls `retain` as the playhead moves, so stale fetches are aborted.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.ts";
import type { SmartOverlay } from "./smartLabels.ts";
import { OVERLAY_BLOCK, overlayStore } from "./smartPlayback.ts";

const RETRY_MS = 3000;

export interface PlaybackOverlays {
  /** The stored outlines of the frame on screen (`shown`), never of the playhead. */
  overlays: SmartOverlay[];
  /** Resolves when frame `index`'s overlay block is cached or known missing (rejects if aborted). */
  ensure: (index: number) => Promise<void>;
  /** Abort overlay fetches that hold none of these frame indices. */
  retain: (indexes: number[]) => void;
}

/** `shown` = index of the frame on screen (null: none). `version` drops the cache (bump it after
 *  the stored series is recomputed). */
export function useSmartPlaybackOverlays(name: string, ids: number[], shown: number | null, version = 0): PlaybackOverlays {
  const mounted = useRef(true);
  const [tick, setTick] = useState(0);
  const [retry, setRetry] = useState(0);  // bumped after a transient failure so the fetch runs again
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const key = `${name}|${version}`;
  const store = useMemo(() => overlayStore(
    (id, start, signal) => api.smartOverlay(name, id, start, OVERLAY_BLOCK, signal),
    OVERLAY_BLOCK,
    {
      onChange: () => { if (mounted.current) setTick((t) => t + 1); },
      onRetry: () => { window.setTimeout(() => { if (mounted.current) setRetry((r) => r + 1); }, RETRY_MS); },
    },
  ), [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => store.abortAll(), [store]);
  const idsRef = useRef(ids);
  idsRef.current = ids;
  const idsKey = ids.join(",");
  // the shown frame's outline when it was not loaded through `ensure` (a smart ROI just added,
  // the cache dropped after a recompute, or a retry after a transient failure)
  useEffect(() => {
    if (shown === null || !ids.length) return;
    store.ensure(ids, shown).catch(() => undefined);
  }, [store, idsKey, shown, retry]);  // eslint-disable-line react-hooks/exhaustive-deps
  const ensure = useCallback((index: number) => (idsRef.current.length ? store.ensure(idsRef.current, index) : Promise.resolve()), [store]);
  const retain = useCallback((indexes: number[]) => store.retain(indexes), [store]);
  // a stable array per (shown frame, loaded data) so the outline decode in ThermalView runs only on change
  const overlays = useMemo(() => (shown === null ? [] : store.pick(ids, shown)), [store, idsKey, shown, tick]);  // eslint-disable-line react-hooks/exhaustive-deps
  return { overlays, ensure, retain };
}
