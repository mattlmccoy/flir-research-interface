// Named presets (spec "Presets"): a visible adjustment, a subset of the thermal camera settings and
// the display settings. Stored on the operator (`/api/presets`, backend `presets.py`); this module is
// the browser's pure side: what applying one would do, whether the current state still matches it,
// and building one from the current state. Nothing here talks to the operator except through the
// setter handed to `writeThermal`.
import { PALETTE_NAMES, type PaletteName } from "./palette.ts";
import type { Range, ScaleMode } from "./scale.ts";
import { adjustEqual, clampAdjust, type VisibleAdjust } from "./visibleAdjust.ts";

/** Display range in a preset: the spec's names (`auto` / `locked` with °C bounds). */
export type PresetRange = { mode: "auto" } | { mode: "locked"; min_c: number; max_c: number };
export interface PresetDisplay { palette: string; range: PresetRange; }
export type ThermalValue = number | string;
export interface Preset {
  name: string;
  visible_adjust: VisibleAdjust;
  /** Writable camera nodes in the camera's own units (K, m, fractions; case index; enum entries). */
  thermal: Record<string, ThermalValue>;
  display: PresetDisplay;
  saved_utc?: string;
}
export interface PresetsDoc { version: number; last_applied: string | null; presets: Preset[]; }
/** The App's own display state: palette, ScaleMode and the manual range. */
export interface ViewDisplay { palette: PaletteName; scaleMode: ScaleMode; manual: Range; }

/** `camera/controls.py` WRITABLE_NODES, in the backend's order. */
export const FLOAT_NODES = ["ObjectEmissivity", "ReflectedTemperature", "AtmosphericTemperature", "ObjectDistance",
  "RelativeHumidity", "ExtOpticsTemperature", "ExtOpticsTransmission"] as const;
export const ENUM_NODES = ["NUCMode", "IRFrameRate"] as const;
export const WRITABLE_NODES: readonly string[] = [...FLOAT_NODES, "CurrentCase", ...ENUM_NODES];

export const NUC_WARNING = "changing the measurement case triggers a NUC";
export const RECORDING_SKIP = "camera settings not applied: a recording is running (visible and display applied)";
export const DISCONNECTED_SKIP = "camera settings not applied: no camera connected (visible and display applied)";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const first = (...vs: unknown[]): unknown => vs.find((v) => v !== null && v !== undefined);

/** The writable node values in a `/api/camera/info` dict and the writable names it has no value
 *  for. Same reading as the backend's `presets.thermal_from_camera_info`. */
export function thermalFromInfo(info: Record<string, unknown> | null | undefined): { values: Record<string, ThermalValue>; leftOut: string[] } {
  const i = info ?? {};
  const nodes = isObj(i.nodes) ? i.nodes : {};
  const params = isObj(i.object_parameters) ? i.object_parameters : {};
  const active = isObj(i.active_case) ? i.active_case : {};
  const found: Record<string, unknown> = {};
  for (const n of FLOAT_NODES) found[n] = params[n];
  found.CurrentCase = first(active.index, nodes.CurrentCase);
  found.NUCMode = first(nodes.NUCMode, i.nuc_mode);
  found.IRFrameRate = first(nodes.IRFrameRate, i.ir_frame_rate);
  const values: Record<string, ThermalValue> = {};
  for (const n of WRITABLE_NODES) {
    const v = found[n];
    if ((typeof v === "number" && Number.isFinite(v)) || typeof v === "string") values[n] = v;
  }
  return { values, leftOut: WRITABLE_NODES.filter((n) => !(n in values)) };
}

/** Equal as camera values: numbers within float32 round-off (the camera stores float32), text exactly. */
function sameValue(a: ThermalValue | undefined, b: ThermalValue | undefined): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(a), Math.abs(b));
  return a !== undefined && a === b;
}

/** P1: preset range ↔ App ScaleMode. `locked` is `manual` with the App's {min, max}. */
export function displayFromView(v: ViewDisplay): PresetDisplay {
  if (v.scaleMode === "auto") return { palette: v.palette, range: { mode: "auto" } };
  const lo = Math.min(v.manual.min, v.manual.max), hi = Math.max(v.manual.min, v.manual.max);
  return { palette: v.palette, range: { mode: "locked", min_c: lo, max_c: hi } };
}

/** The App display state a preset's display asks for. `auto` keeps the current manual range (it
 *  is what "lock" starts from later); a palette this UI does not have keeps the current one. */
export function viewFromDisplay(d: PresetDisplay, current: ViewDisplay): { view: ViewDisplay; warnings: string[] } {
  const known = (PALETTE_NAMES as readonly string[]).includes(d.palette);
  const palette = known ? (d.palette as PaletteName) : current.palette;
  const warnings = known ? [] : [`palette "${d.palette}" is not available here; kept ${current.palette}`];
  const view: ViewDisplay = d.range.mode === "locked"
    ? { palette, scaleMode: "manual", manual: { min: d.range.min_c, max: d.range.max_c } }
    : { palette, scaleMode: "auto", manual: current.manual };
  return { view, warnings };
}

export interface ApplyState {
  recording: boolean;
  cameraConnected: boolean;
  /** The camera's `enum_options` (`/api/camera/info`). */
  enumOptions: Record<string, string[]>;
  /** The camera's current writable values (`thermalFromInfo`); a value equal to it is not written. */
  current: Record<string, ThermalValue>;
}
export interface ApplyPlan {
  visible: VisibleAdjust;
  display: PresetDisplay;
  /** Nodes to write, in order, `CurrentCase` last; null = no camera write at all (recording / no camera). */
  thermal: Array<[string, ThermalValue]> | null;
  /** Preset nodes that will not be written because the camera cannot take them. */
  skipped: string[];
  warnings: string[];
}

/** What applying `preset` does now. Camera settings are left alone while recording or without a
 *  camera; unchanged values are left out; an enum value the camera does not offer is skipped. */
export function applyPlan(preset: Preset, state: ApplyState): ApplyPlan {
  const base = { visible: clampAdjust(preset.visible_adjust), display: preset.display };
  const entries = Object.entries(preset.thermal ?? {});
  if (state.recording || !state.cameraConnected) {
    const warnings = entries.length === 0 ? [] : [state.recording ? RECORDING_SKIP : DISCONNECTED_SKIP];
    return { ...base, thermal: null, skipped: [], warnings };
  }
  const thermal: Array<[string, ThermalValue]> = [];
  const skipped: string[] = [];
  const warnings: string[] = [];
  for (const [node] of entries) {
    if (!WRITABLE_NODES.includes(node)) { skipped.push(node); warnings.push(`${node} is not a writable camera parameter; not written`); }
  }
  for (const node of WRITABLE_NODES) {
    if (!(node in preset.thermal)) continue;
    const v = preset.thermal[node];
    if ((ENUM_NODES as readonly string[]).includes(node)) {
      const opts = state.enumOptions[node];
      if (!opts || !opts.includes(String(v))) {
        skipped.push(node);
        warnings.push(`${node} "${v}" is not offered by this camera${opts ? ` (${opts.join(", ")})` : ""}; not written`);
        continue;
      }
    }
    if (sameValue(v, state.current[node])) continue;
    if (node !== "CurrentCase") thermal.push([node, v]);
  }
  const cc = preset.thermal.CurrentCase;
  if (cc !== undefined && !sameValue(cc, state.current.CurrentCase)) {
    thermal.push(["CurrentCase", cc]);
    warnings.push(NUC_WARNING);
  }
  return { ...base, thermal, skipped, warnings };
}

function sameRange(a: PresetRange, b: PresetRange): boolean {
  if (a.mode === "auto" || b.mode === "auto") return a.mode === b.mode;
  return Math.abs(a.min_c - b.min_c) <= 1e-6 && Math.abs(a.max_c - b.max_c) <= 1e-6;
}

/** True when the current state no longer matches `preset`: a slider, the palette or the range
 *  moved, or (when `thermal` is given) a camera value differs from the preset's. */
export function isModified(
  current: { visible: VisibleAdjust; display: PresetDisplay; thermal?: Record<string, ThermalValue> | null },
  preset: Preset,
): boolean {
  if (!adjustEqual(clampAdjust(current.visible), clampAdjust(preset.visible_adjust))) return true;
  if (current.display.palette !== preset.display.palette || !sameRange(current.display.range, preset.display.range)) return true;
  const t = current.thermal;
  if (!t) return false;
  return Object.entries(preset.thermal ?? {}).some(([n, v]) => !sameValue(v, t[n]));
}

/** A preset from the current state. `thermal` null = no camera (no thermal block); null values are
 *  left out and listed in `omitted` after the names already left out (`omitted` argument). */
export function presetFromState(
  name: string,
  visible: VisibleAdjust,
  display: PresetDisplay,
  thermal: Record<string, ThermalValue | null> | null,
  omitted: string[],
): { preset: Preset; omitted: string[] } {
  const kept: Record<string, ThermalValue> = {};
  const nulls: string[] = [];
  for (const [n, v] of Object.entries(thermal ?? {})) {
    if (v === null) nulls.push(n); else kept[n] = v;
  }
  return {
    preset: { name: name.trim(), visible_adjust: clampAdjust(visible), thermal: kept, display },
    omitted: [...nulls, ...omitted.filter((n) => !nulls.includes(n))],
  };
}

export interface ThermalWriteResult {
  written: string[];
  failed: { node: string; error: string } | null;
  /** Nodes after the failure, not attempted. */
  notWritten: string[];
}

/** Write the plan's nodes one request each, in order, stopping at the first failure, so a failure
 *  part-way says exactly which values the camera took. `set` is `api.setParameters`. */
export async function writeThermal(
  thermal: Array<[string, ThermalValue]>,
  set: (values: Record<string, ThermalValue>) => Promise<unknown>,
): Promise<ThermalWriteResult> {
  const written: string[] = [];
  for (let i = 0; i < thermal.length; i++) {
    const [node, v] = thermal[i];
    try {
      await set({ [node]: v });
      written.push(node);
    } catch (e) {
      return { written, failed: { node, error: String(e) }, notWritten: thermal.slice(i + 1).map(([n]) => n) };
    }
  }
  return { written, failed: null, notWritten: [] };
}

/** One line on a camera write: what changed, what failed, what was not attempted. */
export function writeSummary(r: ThermalWriteResult): string {
  if (!r.failed) return r.written.length ? `camera: wrote ${r.written.join(", ")}` : "camera: already matched the preset";
  const parts = [`camera write failed at ${r.failed.node} (${r.failed.error})`];
  parts.push(r.written.length ? `written: ${r.written.join(", ")}` : "nothing was written");
  if (r.notWritten.length) parts.push(`not written: ${r.notWritten.join(", ")}`);
  return parts.join("; ");
}
