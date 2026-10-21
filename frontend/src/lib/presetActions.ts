// What the preset buttons do, with every effect handed in (state setters, operator calls, the
// confirmation dialog) so the rules are tested without a browser: camera settings only on an
// explicit live apply, never while recording or without a camera, one node per request with
// `CurrentCase` last, and every partial result reported.
import {
  applyPlan,
  displayFromView,
  presetFromState,
  thermalFromInfo,
  viewFromDisplay,
  writeSummary,
  writeThermal,
  NUC_WARNING,
  type Preset,
  type ThermalValue,
  type ViewDisplay,
} from "./presets.ts";
import type { VisibleAdjust } from "./visibleAdjust.ts";

/** One result line of an apply; `warn` lines are things that were not done. */
export interface ApplyLine { text: string; warn: boolean; }

export interface LiveDeps {
  recording: boolean;
  /** Camera status is connected or acquiring. */
  cameraConnected: boolean;
  view: ViewDisplay;
  setVisible: (a: VisibleAdjust) => void;
  setView: (v: ViewDisplay) => void;
  /** `api.info` (read fresh at apply time: the values to compare and the camera's enum options). */
  readInfo: () => Promise<Record<string, unknown>>;
  /** `api.setParameters` (`POST /api/camera/parameters`). */
  setParameters: (values: Record<string, ThermalValue>) => Promise<unknown>;
  confirm: (message: string) => boolean;
  markApplied: (name: string) => Promise<void>;
  /** Called after any camera write was attempted (refresh the camera info). */
  onCameraWritten?: () => void;
}

/** Live "apply": sliders and display at once, then (after a confirmation) the camera settings. */
export async function applyLivePreset(p: Preset, d: LiveDeps): Promise<ApplyLine[]> {
  let info: Record<string, unknown> | null = null;
  let infoError: string | null = null;
  const hasThermal = Object.keys(p.thermal ?? {}).length > 0;
  if (d.cameraConnected && !d.recording && hasThermal) {
    try { info = await d.readInfo(); } catch (e) { infoError = String(e); }
  }
  const plan = applyPlan(p, {
    recording: d.recording,
    cameraConnected: d.cameraConnected && (info !== null || !hasThermal),
    enumOptions: (info?.enum_options as Record<string, string[]> | undefined) ?? {},
    current: thermalFromInfo(info).values,
  });
  d.setVisible(plan.visible);
  const shown = viewFromDisplay(plan.display, d.view);
  d.setView(shown.view);
  const lines: ApplyLine[] = [{ text: `applied "${p.name}": visible sliders and display`, warn: false }];
  for (const w of shown.warnings) lines.push({ text: w, warn: true });
  if (infoError) lines.push({ text: `camera settings not applied: the camera info could not be read (${infoError})`, warn: true });
  else for (const w of plan.warnings) if (w !== NUC_WARNING) lines.push({ text: w, warn: true });
  if (plan.thermal && plan.thermal.length > 0) {
    const list = plan.thermal.map(([n, v]) => `${n} = ${v}`).join("\n");
    const nuc = plan.warnings.includes(NUC_WARNING) ? `\n\nNote: ${NUC_WARNING} and a range switch.` : "";
    if (!d.confirm(`Write ${plan.thermal.length} camera setting${plan.thermal.length === 1 ? "" : "s"} from "${p.name}"?\n\n${list}${nuc}`)) {
      lines.push({ text: "camera settings not written (cancelled)", warn: true });
    } else {
      const r = await writeThermal(plan.thermal, d.setParameters);
      lines.push({ text: writeSummary(r), warn: r.failed !== null });
      d.onCameraWritten?.();
    }
  } else if (plan.thermal && hasThermal && plan.skipped.length === 0) {
    lines.push({ text: "camera: already matches the preset", warn: false });
  }
  try { await d.markApplied(p.name); } catch (e) { lines.push({ text: `could not record "${p.name}" as last applied: ${String(e)}`, warn: true }); }
  return lines;
}

export interface SaveDeps {
  visible: VisibleAdjust;
  view: ViewDisplay;
  /** `api.currentThermal` (409 without a camera). */
  currentThermal: () => Promise<{ thermal: Record<string, ThermalValue | null>; left_out: string[] }>;
  put: (p: Preset) => Promise<void>;
}

const isConflict = (e: unknown) => /^(Error: )?409\b/.test(String(e));

/** "save current as…": the sliders, the display and (with a camera) its writable settings. */
export async function saveCurrentPreset(name: string, d: SaveDeps): Promise<string> {
  let thermal: Record<string, ThermalValue | null> | null = null;
  let leftOut: string[] = [];
  try {
    const r = await d.currentThermal();
    thermal = r.thermal;
    leftOut = r.left_out;
  } catch (e) {
    if (!isConflict(e)) throw e;
  }
  const { preset, omitted } = presetFromState(name, d.visible, displayFromView(d.view), thermal, leftOut);
  await d.put(preset);
  if (thermal === null) return `saved "${preset.name}" without camera settings: no camera connected`;
  return omitted.length ? `saved "${preset.name}"; camera values not read, left out: ${omitted.join(", ")}` : `saved "${preset.name}"`;
}

export interface LookDeps {
  hasVideo: boolean;
  /** The run's adjustment setter (`useRunVisibleAdjust().set`: debounced sidecar save). */
  setAdjust: (a: VisibleAdjust) => void;
  view: ViewDisplay;
  setView: (v: ViewDisplay) => void;
}

/** Playback "apply look": the visible part into this run, the display part into the view. */
export function applyLook(p: Preset, d: LookDeps): ApplyLine[] {
  const lines: ApplyLine[] = [];
  if (d.hasVideo) {
    d.setAdjust(p.visible_adjust);
    lines.push({ text: `"${p.name}": visible adjustment saved for this run, display set; camera settings are not changed`, warn: false });
  } else {
    lines.push({ text: `"${p.name}": display set; this run has no visible video; camera settings are not changed`, warn: false });
  }
  const shown = viewFromDisplay(p.display, d.view);
  d.setView(shown.view);
  for (const w of shown.warnings) lines.push({ text: w, warn: true });
  return lines;
}
