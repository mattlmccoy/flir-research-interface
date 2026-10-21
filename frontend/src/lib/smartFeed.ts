// The operator's live smart ROI feed as the rail shows it (pure; polling lives in useSmartFeed.ts).
// No-false-green: a failed, stale or not-live feed never shows the last good numbers.
import { smartFeedMap, smartReadoutLines, type SmartReadoutEntry } from "./smartReadout.ts";

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

export type SmartTone = "locked" | "holding" | "searching" | "invalid" | "none";
export interface SmartRowView {
  lines: string[];
  /** Colours the state line and the value; "none" = no trustworthy reading at all. */
  tone: SmartTone;
  /** Sample mean °C for the value column, only for a valid, fresh entry. */
  mean: number | null;
  /** Shown next to (or instead of) the value when the entry is not plainly locked. */
  marker: string | null;
}

const none = (line: string): SmartRowView => ({ lines: [line], tone: "none", mean: null, marker: null });

export function smartRowView(feed: SmartFeed | null, id: number, now: number, intervalMs: number): SmartRowView {
  if (!feed) return none("waiting for the operator…");
  if (!feedFresh(feed, now, intervalMs)) return none("no reading: the operator's live feed is unreachable");
  if (!feed.live) return none("operator not live: no current camera frame");
  const e = feed.entries.get(id);
  if (!e) return none("no reading from the operator yet");
  const lines = smartReadoutLines(e);
  if (!e.valid) return { lines, tone: e.state === "searching" ? "searching" : "invalid", mean: null, marker: e.state === "searching" ? "searching" : "not valid" };
  return { lines, tone: e.state === "holding" ? "holding" : "locked", mean: e.sample.mean_c, marker: e.state === "holding" ? "holding" : null };
}

/** One live-plot point for a smart ROI: the operator's sample mean, or NaN (a gap) when the feed
 *  is stale, not live, or the entry is not a valid reading (searching / hold expired). */
export function smartLiveValue(feed: SmartFeed | null, id: number, now: number, intervalMs: number): number {
  return smartRowView(feed, id, now, intervalMs).mean ?? NaN;
}
