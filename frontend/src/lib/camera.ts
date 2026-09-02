/**
 * Camera-controls form model. The camera speaks Kelvin and fractions (docs/radiometry.md);
 * the form speaks °C and percent. Only changed fields are sent, in camera units.
 */
const KELVIN_OFFSET = 273.15;

export interface CameraForm {
  emissivity: number | null;
  reflected_c: number | null;
  atmospheric_c: number | null;
  distance_m: number | null;
  humidity_pct: number | null;
  case_index: number | null;
  nuc_mode: string | null;
  ir_frame_rate: string | null;
}

function num(v: unknown): number | null { return typeof v === "number" && Number.isFinite(v) ? v : null; }
function str(v: unknown): string | null { return typeof v === "string" ? v : null; }
/** The camera stores float32; round to the precision the form edits at so 0.95 is not 0.949999988. */
function round(v: number | null, decimals: number): number | null {
  if (v === null) return null;
  const f = 10 ** decimals;
  return Math.round(v * f) / f;
}
function kToC(v: unknown): number | null { const k = num(v); return k === null ? null : round(k - KELVIN_OFFSET, 2); }

export function formFromInfo(info: Record<string, unknown>): CameraForm {
  const obj = (info.object_parameters ?? {}) as Record<string, unknown>;
  const active = (info.active_case ?? {}) as Record<string, unknown>;
  const hum = num(obj.RelativeHumidity);
  return {
    emissivity: round(num(obj.ObjectEmissivity), 3),
    reflected_c: kToC(obj.ReflectedTemperature),
    atmospheric_c: kToC(obj.AtmosphericTemperature),
    distance_m: round(num(obj.ObjectDistance), 3),
    humidity_pct: hum === null ? null : round(hum * 100, 1),
    case_index: num(active.index),
    nuc_mode: str(info.nuc_mode),
    ir_frame_rate: str(info.ir_frame_rate),
  };
}

const EPS = 1e-9;
function changed(a: number | string | null, b: number | string | null): boolean {
  if (a === null) return false;
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) > EPS;
  return a !== b;
}

/** Node values (camera units) for every field that differs from `base`; null fields are never sent. */
export function valuesFromForm(form: CameraForm, base: CameraForm): Record<string, number | string> {
  const out: Record<string, number | string> = {};
  if (changed(form.emissivity, base.emissivity)) out.ObjectEmissivity = form.emissivity as number;
  if (changed(form.reflected_c, base.reflected_c)) out.ReflectedTemperature = (form.reflected_c as number) + KELVIN_OFFSET;
  if (changed(form.atmospheric_c, base.atmospheric_c)) out.AtmosphericTemperature = (form.atmospheric_c as number) + KELVIN_OFFSET;
  if (changed(form.distance_m, base.distance_m)) out.ObjectDistance = form.distance_m as number;
  if (changed(form.humidity_pct, base.humidity_pct)) out.RelativeHumidity = (form.humidity_pct as number) / 100;
  if (changed(form.case_index, base.case_index)) out.CurrentCase = form.case_index as number;
  if (changed(form.nuc_mode, base.nuc_mode)) out.NUCMode = form.nuc_mode as string;
  if (changed(form.ir_frame_rate, base.ir_frame_rate)) out.IRFrameRate = form.ir_frame_rate as string;
  return out;
}
