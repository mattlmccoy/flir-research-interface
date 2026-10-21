// Polls the operator's live ROI feed for smart ROI readouts (the operator is the single source of
// truth for smart ROI numbers; spec §6). Only runs while `enabled` (live page with a smart ROI).
import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { smartFeedMap, type SmartReadoutEntry } from "./smartReadout.ts";

/** `ok` false = the last poll failed: no reading, which must never look like a healthy one. */
export interface SmartFeed { ok: boolean; entries: Map<number, SmartReadoutEntry>; }

export const SMART_FEED_INTERVAL_MS = 500;

export function useSmartFeed(enabled: boolean, intervalMs = SMART_FEED_INTERVAL_MS): SmartFeed | null {
  const [feed, setFeed] = useState<SmartFeed | null>(null);
  useEffect(() => {
    if (!enabled) { setFeed(null); return; }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      api.liveRoiTemps()
        .then((p) => { if (alive) setFeed({ ok: true, entries: smartFeedMap(p) }); })
        .catch(() => { if (alive) setFeed({ ok: false, entries: new Map() }); })
        .finally(() => { if (alive) timer = setTimeout(tick, intervalMs); });
    };
    tick();
    return () => { alive = false; if (timer !== undefined) clearTimeout(timer); };
  }, [enabled, intervalMs]);
  return feed;
}
