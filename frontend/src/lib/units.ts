/** Display units for temperatures (ResearchIR units selector): °C, K, °F or raw counts. */
export type Units = "C" | "K" | "F" | "counts";
export const UNIT_LABEL: Record<Units, string> = { C: "°C", K: "K", F: "°F", counts: "counts" };
export const UNITS: readonly Units[] = ["C", "K", "F", "counts"];
export interface Conversion { kelvin_per_count: number; kelvin_offset: number; }

export function convertTemp(c: number, units: Units, conv: Conversion | null): number {
  switch (units) {
    case "K": return c + 273.15;
    case "F": return c * 9 / 5 + 32;
    case "counts": return conv ? Math.round((c + conv.kelvin_offset) / conv.kelvin_per_count) : NaN;
    default: return c;
  }
}

export function fmtTemp(c: number, units: Units, conv: Conversion | null, digits = 2): string {
  if (Number.isNaN(c)) return "n/a";
  const v = convertTemp(c, units, conv);
  if (units === "counts") return Number.isNaN(v) ? "n/a" : String(v);
  return `${v.toFixed(digits)} ${UNIT_LABEL[units]}`;
}
