// Polls the operator's live ROI feed for smart ROI readouts (the operator is the single source of
// truth for smart ROI numbers; spec §6). Only runs while `enabled` (live page with a smart ROI).
import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { smartFeedFrom, type SmartFeed } from "./smartFeed.ts";

export const SMART_FEED_INTERVAL_MS = 500;
/** A poll that has not answered by then is abandoned (failed), so a hung request can never keep
 *  the last good numbers on screen; the rail also treats a feed older than 2 intervals as stale. */
export const SMART_FEED_TIMEOUT_MS = 1500;

export function useSmartFeed(enabled: boolean, intervalMs = SMART_FEED_INTERVAL_MS): SmartFeed | null {
  const [feed, setFeed] = useState<SmartFeed | null>(null);
  useEffect(() => {
    if (!enabled) { setFeed(null); return; }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      api.liveRoiTemps(AbortSignal.timeout(SMART_FEED_TIMEOUT_MS))
        .then((p) => { if (alive) setFeed(smartFeedFrom(p, Date.now())); })
        .catch(() => { if (alive) setFeed({ ok: false, at: Date.now(), live: false, entries: new Map() }); })
        .finally(() => { if (alive) timer = setTimeout(tick, intervalMs); });
    };
    tick();
    return () => { alive = false; if (timer !== undefined) clearTimeout(timer); };
  }, [enabled, intervalMs]);
  return feed;
}
