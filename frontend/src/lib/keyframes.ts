/** Hover-scrub helpers for the Experiments grid (spec §4). */

export function keyframeIndex(x: number, width: number, count: number): number {
  if (width <= 0 || count <= 1) return 0;
  const i = Math.floor((x / width) * count);
  return Math.min(Math.max(i, 0), count - 1);
}

/** CSS background-position for tile k of a horizontal strip with background-size count*100%. */
export function keyframeBackgroundPosition(k: number, count: number): string {
  if (count <= 1) return "0% 0";
  return `${(k / (count - 1)) * 100}% 0`;
}

export function formatSeconds(t: number): string {
  if (t < 60) return `${t.toFixed(2)} s`;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
