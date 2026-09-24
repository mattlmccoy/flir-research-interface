// What the playback plot's right-hand axis shows from a run's control trace. The axis has ONE unit,
// so RF power (W) and the AIT matching-network capacitor positions (%) are alternatives, never
// mixed on one scale. Gaps (null samples) become NaN so they plot as breaks, not zeros. Cap colors
// are tokens the ROI trace palette never uses, so a cap line cannot be mistaken for a temperature.

export type RightAxisMode = "off" | "rf" | "caps";

export interface ControlLike {
  t_s: number[];
  forward_w?: (number | null)[];
  tune_cap_percent?: (number | null)[];
  load_cap_percent?: (number | null)[];
}

export interface AxisTrace { id: number; label: string; color: string; t: number[]; v: number[]; }

const has = (xs: (number | null)[] | undefined): xs is (number | null)[] =>
  Array.isArray(xs) && xs.some((v) => v != null);
const nanGaps = (xs: (number | null)[]): number[] => xs.map((v) => (v == null ? NaN : v));

/** The right-axis choices this run actually has data for (all-null columns are not offered). */
export function rightAxisOptions(c: ControlLike | null | undefined): Exclude<RightAxisMode, "off">[] {
  if (!c) return [];
  const out: Exclude<RightAxisMode, "off">[] = [];
  if (has(c.forward_w)) out.push("rf");
  if (has(c.tune_cap_percent) || has(c.load_cap_percent)) out.push("caps");
  return out;
}

export function rightAxis(
  c: ControlLike | null | undefined, mode: RightAxisMode,
): { traces: AxisTrace[]; units: string } {
  if (!c || mode === "off" || !rightAxisOptions(c).includes(mode)) return { traces: [], units: "" };
  if (mode === "rf") {
    return {
      units: "W",
      traces: [{ id: -100, label: "RF power", color: "var(--warn)", t: c.t_s, v: nanGaps(c.forward_w!) }],
    };
  }
  const traces: AxisTrace[] = [];
  if (has(c.tune_cap_percent)) {
    traces.push({ id: -101, label: "tune cap", color: "var(--fg-strong)", t: c.t_s, v: nanGaps(c.tune_cap_percent) });
  }
  if (has(c.load_cap_percent)) {
    traces.push({ id: -102, label: "load cap", color: "var(--err)", t: c.t_s, v: nanGaps(c.load_cap_percent) });
  }
  return { units: "%", traces };
}
