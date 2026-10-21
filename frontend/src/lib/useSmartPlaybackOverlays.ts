// Fetches and caches a recorded run's stored smart ROI outlines, a block of frames at a time, so
// stepping or playing never waits per frame (GET /api/experiments/{name}/smart-roi/{id}/overlay).
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api.ts";
import type { SmartOverlay } from "./smartLabels.ts";
import { OVERLAY_BLOCK, overlayBlock, overlayOnError, pickOverlays, type OverlayCache } from "./smartPlayback.ts";

const RETRY_MS = 3000;

/** Overlays for frame `index` of run `name` for the given smart ROI ids. `version` drops the cache
 *  (bump it after the stored series is recomputed). */
export function useSmartPlaybackOverlays(name: string, ids: number[], index: number, version = 0): SmartOverlay[] {
  const cache = useRef<OverlayCache>(new Map());
  const inflight = useRef(new Set<string>());
  const mounted = useRef(true);
  const [tick, setTick] = useState(0);
  const [retry, setRetry] = useState(0);  // bumped after a transient failure so the fetch runs again
  const key = `${name}|${version}`;
  const keyRef = useRef(key);
  if (keyRef.current !== key) { keyRef.current = key; cache.current = new Map(); inflight.current = new Set(); }
  const idsKey = ids.join(",");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!ids.length) return;
    const start = overlayBlock(index, OVERLAY_BLOCK);
    const want = [start];
    if (index - start >= OVERLAY_BLOCK - 20) want.push(start + OVERLAY_BLOCK);  // prefetch while playing
    const c = cache.current, busy = inflight.current;
    for (const id of ids) for (const b of want) {
      const k = `${id}:${b}`;
      if (c.has(k) || busy.has(k)) continue;
      busy.add(k);
      api.smartOverlay(name, id, b, OVERLAY_BLOCK)
        .then((list) => { c.set(k, list); })
        .catch((e: unknown) => {
          if (overlayOnError(e) === "missing") c.set(k, "missing");  // not computed yet: no outline
          else window.setTimeout(() => { if (mounted.current) setRetry((r) => r + 1); }, RETRY_MS);
        })
        .finally(() => { busy.delete(k); if (mounted.current) setTick((t) => t + 1); });
    }
  }, [name, idsKey, index, version, retry]);  // eslint-disable-line react-hooks/exhaustive-deps
  // a stable array per (frame, loaded data) so the outline decode in ThermalView runs only on change
  return useMemo(() => pickOverlays(cache.current, ids, index, OVERLAY_BLOCK), [key, idsKey, index, tick]);  // eslint-disable-line react-hooks/exhaustive-deps
}
