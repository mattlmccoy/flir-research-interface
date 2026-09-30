/** Maps thermal playback time onto the recorded visible segments.
 *
 * The operator places each segment on the thermal clock (`t_start_s`, from the segment's host launch
 * time vs thermal frame 0; backend playback/visible_timing.py) and serves that as
 * `info.visible_timeline`. An older operator only has visible.json, whose `offset_s` counts from the
 * first segment, so there visible t=0 is taken as thermal t=0 (seconds off with pre-trigger). */

export interface VisibleSegment { index: number; file: string; offset_s?: number; t_start_s?: number; duration_s?: number | null; }
export interface VisibleGap { after_segment: number; start_s: number; duration_s: number; }
export interface VisibleInfo { file?: string | null; segments?: VisibleSegment[] | null; }

/** A file's frame 0 is sometimes torn (7 of 18 runs up to 2026-09-30; likely the opening keyframe
 *  split across two packets, unverified); from 0.07 s on it decodes clean. Never show earlier than this. */
export const FRAME0_SKIP_S = 0.25;

const startOf = (s: VisibleSegment): number => s.t_start_s ?? s.offset_s ?? 0;

/** Which segment covers thermal time `t` and where inside it; null inside a stream gap.
 *  A recording made before segmenting is one file whose time equals thermal time. Before the video
 *  starts, and at every segment's start, the first clean frame is shown. The last segment runs on
 *  (the video holds its final frame), as the single-file player always did. */
export function visibleSegmentAt(vis: VisibleInfo, t: number): { index: number; local: number } | null {
  const segs = vis.segments;
  if (!segs || segs.length === 0) return { index: 0, local: Math.max(t, FRAME0_SKIP_S) };
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const next = segs[i + 1];
    const start = startOf(s);
    const end = s.duration_s ? start + s.duration_s : next ? startOf(next) : Infinity;
    if (t < start) return i === 0 ? { index: s.index, local: FRAME0_SKIP_S } : null;
    if (t < end || !next) return { index: s.index, local: Math.max(t - start, FRAME0_SKIP_S) };
  }
  return null;
}

/** The segments playback should follow: the operator's thermal-clock timeline when it sends one. */
export function visibleForPlayback(info: { visible?: VisibleInfo | null; visible_timeline?: VisibleSegment[] | null }): VisibleInfo | null {
  const vis = info.visible ?? null;
  if (!vis) return null;
  return info.visible_timeline ? { file: vis.file, segments: info.visible_timeline } : vis;
}
