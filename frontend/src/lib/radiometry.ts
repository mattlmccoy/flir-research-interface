/**
 * FLIR temperature-linear decode, mirroring backend/radiometry/temperature_linear.py.
 * T[K] = counts * kelvinPerCount ; T[°C] = T[K] - kelvinOffset.
 * `kelvinPerCount === null` means the stream is not temperature-linear: return NaN everywhere
 * rather than pretend counts are temperatures.
 */
export function countsToCelsius(
  counts: Uint16Array,
  kelvinPerCount: number | null,
  kelvinOffset: number,
): Float32Array {
  const out = new Float32Array(counts.length);
  if (kelvinPerCount === null) {
    out.fill(NaN);
    return out;
  }
  for (let i = 0; i < counts.length; i++) out[i] = counts[i] * kelvinPerCount - kelvinOffset;
  return out;
}
