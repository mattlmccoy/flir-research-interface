/**
 * Detects over-range pixels in TemperatureLinear Mono16 counts: pixels the camera could not
 * represent because the scene exceeded its range.
 *   - saturated: count at/above the 16-bit ceiling (scene hotter than the camera's range);
 *   - wrapped: a count that overflowed 16 bits and now reads far colder than physically possible
 *     (the "hot region shows as cold" artefact), flagged whatever the rest of the frame reads: a
 *     small hot spot (an arc) can wrap while nothing around it is hot. Below -13 °C never occurs
 *     in this lab, so this only ever marks a reading invalid, never healthy. The true temperature
 *     of these pixels is unrecoverable — flagging keeps them from rendering as false cold and from
 *     poisoning ROI statistics and the auto color range.
 */
export const SAT_HI = 65000; // near uint16 max
const FLOOR_C = -13; // implausibly cold in this lab → a wrapped reading (26000 counts at 10 mK)

export interface OverRange { mask: Uint8Array; saturated: number; wrapped: number; }

/** `kelvinPerCount` is the frame's TemperatureLinear scale (0.01 or 0.1): the floor is a
 *  temperature, judged in the frame's own counts. */
export function overRangeMask(counts: Uint16Array, _w: number, _h: number, kelvinPerCount = 0.01): OverRange | null {
  const floor = Math.floor((FLOOR_C + 273.15) / kelvinPerCount);
  let saturated = 0, wrapped = 0;
  const mask = new Uint8Array(counts.length);
  for (let i = 0; i < counts.length; i++) {
    const v = counts[i];
    if (v >= SAT_HI) { mask[i] = 1; saturated++; }
    else if (v <= floor) { mask[i] = 1; wrapped++; }
  }
  return saturated || wrapped ? { mask, saturated, wrapped } : null;
}
