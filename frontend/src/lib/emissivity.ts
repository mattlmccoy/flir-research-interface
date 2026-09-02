/**
 * Per-ROI emissivity / reflected-temperature re-correction, mirroring the backend
 * radiometry/emissivity.py exactly.
 *
 * The camera's temperature-linear output already assumes its global ObjectEmissivity and
 * ReflectedTemperature. FLIR's signal model (atmosphere ≈ transparent at bench distance):
 *   W_meas = ε·W(T_obj) + (1 − ε)·W(T_refl),   W(T) = R / (exp(B/T) − F)
 * Invert with the camera's parameters to recover W_meas, then solve again with the ROI's own
 * ε and T_refl. R, B, F come from the camera (metadata camera.calibration_constants).
 */
export interface Radiometry { R: number; B: number; F: number; epsCam: number; treflCamK: number; }

export function radiance(tK: number, r: Radiometry): number { return r.R / (Math.exp(r.B / tK) - r.F); }
export function temperatureK(w: number, r: Radiometry): number { return r.B / Math.log(r.R / w + r.F); }

/** °C as the camera reported it → °C for emissivity `eps` and reflected temperature `treflK`. */
export function recorrectCelsius(tC: number, r: Radiometry, eps: number, treflK: number): number {
  if (Number.isNaN(tC)) return NaN;
  const wMeas = r.epsCam * radiance(tC + 273.15, r) + (1 - r.epsCam) * radiance(r.treflCamK, r);
  const wObj = (wMeas - (1 - eps) * radiance(treflK, r)) / eps;
  return wObj > 0 ? temperatureK(wObj, r) - 273.15 : NaN;
}

/** Build the camera-side parameters from a /api/camera/info or metadata.json `camera` block. */
export function radiometryFromCamera(cam: Record<string, unknown> | null | undefined): Radiometry | null {
  if (!cam) return null;
  const cc = cam.calibration_constants as Record<string, unknown> | undefined;
  const op = cam.object_parameters as Record<string, unknown> | undefined;
  const R = Number(cc?.R), B = Number(cc?.B), F = Number(cc?.F);
  const epsCam = Number(op?.ObjectEmissivity), treflCamK = Number(op?.ReflectedTemperature);
  if (![R, B, F, epsCam, treflCamK].every((x) => Number.isFinite(x) && x > 0)) return null;
  return { R, B, F, epsCam, treflCamK };
}
