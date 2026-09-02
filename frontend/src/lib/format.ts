/** Shared display formatters for temperature and misc scalar values. */

export function fmtCelsius(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(2)} °C`;
}

export function fmtAny(v: unknown): string {
  return v == null ? "—" : typeof v === "number" ? v.toFixed(2) : String(v);
}

export function kelvinToCelsiusLabel(v: unknown): string {
  return typeof v === "number" ? `${(v - 273.15).toFixed(1)} °C` : "—";
}
