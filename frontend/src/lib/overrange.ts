/**
 * Detects over-range pixels in TemperatureLinear Mono16 counts: pixels the camera could not
 * represent because the scene exceeded its range.
 *   - saturated: count at/above the 16-bit ceiling (scene hotter than the camera's range);
 *   - wrapped: a count that overflowed 16 bits and now reads far colder than physically possible
 *     (the "hot region shows as cold" artefact). Wrapped pixels are only flagged when the frame is
 *     clearly hot (its peak is well into the upper range), so a genuinely cold scene is never
 *     touched. The true temperature of these pixels is unrecoverable — flagging keeps them from
 *     rendering as false cold and from poisoning ROI statistics and the auto colour range.
 */
export const SAT_HI = 65000; // near uint16 max
const FLOOR = 26000; // ~ -13 °C in 10 mK counts: implausibly cold in a hot scene → wrapped
const HOT_MAX = 45000; // ~ 177 °C: the frame is hot enough for over-range/wrap to be plausible

export interface OverRange { mask: Uint8Array; saturated: number; wrapped: number; }

export function overRangeMask(counts: Uint16Array, _w: number, _h: number): OverRange | null {
  let saturated = 0, wrapped = 0, maxCount = 0;
  const mask = new Uint8Array(counts.length);
  for (let i = 0; i < counts.length; i++) {
    const v = counts[i];
    if (v > maxCount) maxCount = v;
    if (v >= SAT_HI) { mask[i] = 1; saturated++; }
  }
  if (maxCount >= HOT_MAX) {
    for (let i = 0; i < counts.length; i++) {
      if (mask[i]) continue;
      if (counts[i] <= FLOOR) { mask[i] = 1; wrapped++; }
    }
  }
  return saturated || wrapped ? { mask, saturated, wrapped } : null;
}
