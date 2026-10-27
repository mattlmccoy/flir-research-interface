// The operator's live smart ROI feed as the rail shows it (pure; polling lives in useSmartFeed.ts).
// No-false-green: a failed, stale or not-live feed never shows the last good numbers.
import { isOverRange, parseSmartOver, smartFeedMap, smartSummary, type SmartReadoutEntry, type SmartState } from "./smartReadout.ts";

/** One poll's result. `ok` false = the poll failed; `at` = when it completed (ms); `live` = the
 *  operator had a current camera frame (payload `live`). */
export interface SmartFeed { ok: boolean; at: number; live: boolean; entries: Map<number, SmartReadoutEntry>; }

export function smartFeedFrom(payload: unknown, at: number): SmartFeed {
  const live = !!payload && typeof payload === "object" && (payload as { live?: unknown }).live === true;
  return { ok: true, at, live, entries: smartFeedMap(payload) };
}

/** True when the last poll succeeded within two poll intervals of `now`. */
export function feedFresh(feed: SmartFeed | null, now: number, intervalMs: number): boolean {
  return !!feed && feed.ok && now - feed.at <= 2 * intervalMs;
}

/** The entries the on-image chips may take numbers from: only a fresh feed from a live operator
 *  (otherwise undefined, so a hung poll or a stopped camera never leaves old numbers on the image). */
export function smartChipFeed(feed: SmartFeed | null, now: number, intervalMs: number): Map<number, SmartReadoutEntry> | undefined {
  return feed && feedFresh(feed, now, intervalMs) && feed.live ? feed.entries : undefined;
}

/** "over": located, but some pixels are over the camera's range: bounded numbers in the warn tone,
 *  never the locked (healthy) one. */
export type SmartTone = "locked" | "holding" | "searching" | "invalid" | "none" | "over";
export interface SmartRowView {
  /** The collapsed row: one line (state, numbers only when valid, and the stale / ≈ markers). */
  summary: string;
  /** The reading behind the row, for the expanded table (smartReadout.ts smartDetails); null when
   *  there is no reading at all. */
  entry: SmartReadoutEntry | null;
  /** Full explanations of the markers (≈ downsampled, stale), shown when expanded. */
  notes: string[];
  /** Colours the state line and the value; "none" = no trustworthy reading at all. */
  tone: SmartTone;
  /** Sample mean °C for the value column, only for a valid, fresh entry. */
  mean: number | null;
  /** Shown next to (or instead of) the value when the entry is not plainly locked. */
  marker: string | null;
}

const none = (line: string): SmartRowView => ({ summary: line, entry: null, notes: [], tone: "none", mean: null, marker: null });

/** The live frame's overlay for one smart ROI (WS frame header `smart[i]`); only its state and its
 *  `over` block are read here. */
export interface SmartFrameOverlay { state: SmartState; over?: unknown; }

/** The over-range view of a row (live and playback): bounded numbers, warn tone, no plotted mean. */
export function overRow(row: { summary: string; entry: SmartReadoutEntry; notes: string[] }, marks: string[] = []): SmartRowView {
  return { ...row, tone: "over", mean: null, marker: ["over range", ...marks].join(" ") };
}

/** One live rail row. Normal readings come from the operator's feed; while the frame on screen has
 *  over-range pixels in the sample, the bounded numbers come from that frame's overlay (`overlay`,
 *  the UI-only channel: the feed keeps reporting such an ROI invalid with no numbers), and only
 *  while the feed itself is fresh and live. */
export function smartRowView(feed: SmartFeed | null, id: number, now: number, intervalMs: number, overlay?: SmartFrameOverlay | null): SmartRowView {
  if (!feed) return none("waiting for the operator…");
  if (!feedFresh(feed, now, intervalMs)) return none("no reading: the operator's live feed is unreachable");
  if (!feed.live) return none("operator not live: no current camera frame");
  const fe = feed.entries.get(id);
  if (!fe) return none("no reading from the operator yet");
  const over = overlay && overlay.state !== "searching" ? parseSmartOver(overlay.over) : null;
  let e: SmartReadoutEntry = fe;
  if (over && over.sample.over_px > 0) {
    // the frame on screen is over range: never pair it with the (lagging) feed's numbers
    e = { ...fe, state: overlay!.state, valid: false, over_range: true, dims: null, over };
  } else if (over && fe.state === overlay!.state) {
    e = { ...fe, over };  // only a ring is over range: its bounds for the details
  }
  const row = { summary: smartSummary(e), entry: e, notes: [] };
  if (isOverRange(e)) return overRow(row);
  if (!e.valid) return { ...row, tone: e.state === "searching" ? "searching" : "invalid", mean: null, marker: e.state === "searching" ? "searching" : "not valid" };
  return { ...row, tone: e.state === "holding" ? "holding" : "locked", mean: e.sample.mean_c, marker: e.state === "holding" ? "holding" : null };
}

/** One live-plot point for a smart ROI: the operator's sample mean, or NaN (a gap) when the feed
 *  is stale, not live, or the entry is not a valid reading (searching / hold expired). */
export function smartLiveValue(feed: SmartFeed | null, id: number, now: number, intervalMs: number): number {
  return smartRowView(feed, id, now, intervalMs).mean ?? NaN;
}
