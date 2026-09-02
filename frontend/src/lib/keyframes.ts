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
  // Round to the precision each branch displays before deciding which branch applies,
  // so a value like 59.996 (which rounds to "60.0") reports as "1:00.0" instead of "60.00 s".
  if (Math.round(t * 100) / 100 < 60) return `${t.toFixed(2)} s`;
  const rounded = Math.round(t * 10) / 10;
  const m = Math.floor(rounded / 60);
  const s = rounded - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
