/** Pure helpers for playback pacing and cursor handling. */

const MAX_GAP_MS = 2000;

/** Milliseconds to wait before showing the next frame, from recorded relative times and speed. */
export function nextFrameDelayMs(tPrevS: number, tNextS: number, speed: number): number {
  if (!Number.isFinite(speed) || speed <= 0) return 0;
  const dt = (tNextS - tPrevS) * 1000;
  if (!(dt > 0)) return 0;
  return Math.min(dt, MAX_GAP_MS) / speed;
}

export function clampIndex(i: number, n: number): number {
  if (n <= 0) return 0;
  return Math.min(Math.max(Math.trunc(i), 0), n - 1);
}

export function speedLabel(speed: number): string {
  return Number.isFinite(speed) ? `${speed}×` : "max";
}

export const SPEEDS: number[] = [0.25, 0.5, 1, 2, 4, Infinity];
