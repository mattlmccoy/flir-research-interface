// What the playback plot's right-hand axis shows from a run's control trace. The axis has ONE unit,
// so RF power (W) and the AIT matching-network capacitor positions (%) are alternatives, never
// mixed on one scale. Gaps (null samples) become NaN so they plot as breaks, not zeros. Control
// lines use CONTROL_STYLE: hues outside the ROI palette AND a dash pattern, so an RF or cap line
// can never be mistaken for an ROI temperature (RF power used to share the amber of ROI #2).

export type RightAxisMode = "off" | "rf" | "caps";

export interface ControlLike {
  t_s: number[];
  forward_w?: (number | null)[];
  tune_cap_percent?: (number | null)[];
  load_cap_percent?: (number | null)[];
}

export interface AxisTrace { id: number; label: string; color: string; dash?: number[]; t: number[]; v: number[]; }

/** Line style of each control/CXN series. Colors are not in COLOR_PRESETS / TRACE_TOKENS, event
 *  marker colors or the cursor, and every control line is dashed (ROI temperatures are solid). */
export const CONTROL_STYLE = {
  rf: { color: "#ffe600", dash: [8, 4] },        // RF forward power (W)
  tune: { color: "#a0f0ff", dash: [2, 3] },      // AIT tune capacitor (%)
  load: { color: "#ff7a00", dash: [9, 3, 2, 3] }, // AIT load capacitor (%)
  setpoint: { color: "#c8ccd4", dash: [4, 4] },  // closed-loop setpoint (°C)
} as const;

const style = (k: keyof typeof CONTROL_STYLE) => ({ color: CONTROL_STYLE[k].color, dash: [...CONTROL_STYLE[k].dash] });
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
      traces: [{ id: -100, label: "RF power", ...style("rf"), t: c.t_s, v: nanGaps(c.forward_w!) }],
    };
  }
  const traces: AxisTrace[] = [];
  if (has(c.tune_cap_percent)) {
    traces.push({ id: -101, label: "tune cap", ...style("tune"), t: c.t_s, v: nanGaps(c.tune_cap_percent) });
  }
  if (has(c.load_cap_percent)) {
    traces.push({ id: -102, label: "load cap", ...style("load"), t: c.t_s, v: nanGaps(c.load_cap_percent) });
  }
  return { units: "%", traces };
}
