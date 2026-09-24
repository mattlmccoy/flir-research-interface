/** Maps thermal playback time onto the recorded visible segments (visible.json `segments`). */

export interface VisibleSegment { index: number; file: string; offset_s: number; duration_s?: number | null; }
export interface VisibleGap { after_segment: number; start_s: number; duration_s: number; }
export interface VisibleInfo { file?: string | null; segments?: VisibleSegment[] | null; }

/** Which segment covers thermal time `t` and where inside it; null inside a stream gap.
 *  A recording made before segmenting is one file whose time equals thermal time. The last
 *  segment runs on (the video holds its final frame), as the single-file player always did. */
export function visibleSegmentAt(vis: VisibleInfo, t: number): { index: number; local: number } | null {
  const segs = vis.segments;
  if (!segs || segs.length === 0) return { index: 0, local: t };
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const next = segs[i + 1];
    const end = s.duration_s ? s.offset_s + s.duration_s : next ? next.offset_s : Infinity;
    if (t < s.offset_s) return i === 0 ? { index: s.index, local: 0 } : null;
    if (t < end || !next) return { index: s.index, local: t - s.offset_s };
  }
  return null;
}
