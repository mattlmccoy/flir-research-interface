// Playback frame loading: frames come in blocks of FRAME_BLOCK (~37 MB at 640×480), cached around
// the playhead. Blocks the playhead no longer needs are aborted (frameBlocks.ts), and a frame is
// shown only together with its smart ROI outline (the overlay block is requested first and both
// are awaited; ensureLatest survives the overlay store being replaced after a recompute).
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { api } from "./api.ts";
import { blockLoader, blockOf, ensureLatest, loadFailure, wantedBlocks } from "./frameBlocks.ts";
import { decodeFrameBlock, type FrameMessage } from "./protocol.ts";

export const FRAME_BLOCK = 60;
/** Prefetch the next block once the playhead is this many frames from the end of its block. */
const LEAD = 20;

/** The smart ROI overlay side (useSmartPlayback), read through a ref so it can be wired after. */
export interface FrameOverlays {
  ensureOverlays: (index: number) => Promise<void>;
  retainOverlays: (indexes: number[]) => void;
}

export interface FrameBlocks {
  /** The frame on screen (the last one fully loaded with its outline), or null. */
  frame: FrameMessage | null;
  status: "loading" | "ready" | "error";
  error: string | null;
  load: (i: number) => Promise<FrameMessage>;
  /** Load the playhead's frame again after an error. */
  retry: () => void;
}

/** `rf`: frames must carry the RF-banding display copy (a cached frame without one is refetched).
 *  `active`: the run's info is loaded and `n` is its frame count. */
export function useFrameBlocks({ name, n, index, rf, active, overlays }: {
  name: string; n: number; index: number; rf: boolean; active: boolean; overlays: MutableRefObject<FrameOverlays>;
}): FrameBlocks {
  const cache = useRef(new Map<number, FrameMessage>());
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => { cache.current.clear(); }, [name]);

  const loader = useMemo(() => blockLoader(
    (start, signal) => api.frameBlock(name, start, FRAME_BLOCK, rf, signal),
    (_start, buf: ArrayBuffer) => {
      for (const m of decodeFrameBlock(buf)) {
        const idx = (m.header as { index?: number }).index;
        if (typeof idx === "number") cache.current.set(idx, m);
      }
      // keep the cache bounded to a few blocks around the play head
      if (cache.current.size > FRAME_BLOCK * 4) {
        const keys = [...cache.current.keys()].sort((a, b) => a - b);
        for (const k of keys.slice(0, keys.length - FRAME_BLOCK * 3)) cache.current.delete(k);
      }
    },
  ), [name, rf]);
  useEffect(() => () => loader.abortAll(), [loader]);

  const load = useCallback(async (i: number): Promise<FrameMessage> => {
    const overlay = ensureLatest(() => overlays.current.ensureOverlays, i);  // first: small, must not queue
    const hit = cache.current.get(i);
    await Promise.all([overlay, hit && (!rf || hit.display) ? undefined : loader.ensure(blockOf(i, FRAME_BLOCK))]);
    const m = cache.current.get(i);
    if (!m) throw new Error(`frame ${i} not returned`);
    return m;
  }, [loader, rf, overlays]);

  useEffect(() => {
    if (!active || n === 0) return;
    let alive = true;
    // the playhead's block, plus the next one near its end so playback never waits; abort the rest
    const want = wantedBlocks(index, n, FRAME_BLOCK, LEAD);
    loader.retain(want);
    overlays.current.retainOverlays([index, ...want]);
    const hit = cache.current.get(index);
    if (!hit || (rf && !hit.display)) setStatus("loading");  // only show the spinner when we actually have to fetch
    load(index)
      .then((m) => { if (alive) { setFrame(m); setStatus("ready"); setError(null); } })
      .catch((e: unknown) => {
        const msg = loadFailure(e, alive);
        if (msg !== null) { setStatus("error"); setError(msg); }
      });
    for (const b of want.slice(1)) {
      void overlays.current.ensureOverlays(b).catch(() => undefined);
      void loader.ensure(b).catch(() => undefined);
    }
    return () => { alive = false; };
  }, [index, active, n, load, loader, reload]);  // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback(() => { cache.current.delete(index); setReload((r) => r + 1); }, [index]);
  return { frame, status, error, load, retry };
}
