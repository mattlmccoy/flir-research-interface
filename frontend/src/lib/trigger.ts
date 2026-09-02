/** Armed-recording trigger: form ↔ operator object (mirrors backend recording/trigger.py). */
export type StartKind = "manual" | "after" | "threshold";
export type EndKind = "manual" | "frames" | "duration" | "threshold";
export type Stat = "value" | "mean" | "min" | "max";
export type Direction = "rising" | "falling";

export interface TriggerForm {
  startKind: StartKind; afterS: number; roi: number | null; stat: Stat; level: number; direction: Direction; sustain: number;
  endKind: EndKind; frames: number; seconds: number; endRoi: number | null; endStat: Stat; endLevel: number; endDirection: Direction;
  pretrigger: number; maxSeconds: number;
}
export const DEFAULT_TRIGGER_FORM: TriggerForm = Object.freeze({
  startKind: "threshold", afterS: 5, roi: null, stat: "max", level: 40, direction: "rising", sustain: 3,
  endKind: "duration", frames: 300, seconds: 60, endRoi: null, endStat: "max", endLevel: 40, endDirection: "falling",
  pretrigger: 2, maxSeconds: 1800,
}) as TriggerForm;

export interface Threshold { kind: "threshold"; roi?: number; stat: Stat; level_c: number; direction: Direction; sustain_frames: number; }
export type StartSpec = { kind: "manual" } | { kind: "after"; after_s: number } | Threshold;
export type EndSpec = { kind: "manual" } | { kind: "frames"; frames: number } | { kind: "duration"; seconds: number } | Threshold;
export interface TriggerSpec { start: StartSpec; end: EndSpec; pretrigger_s: number; max_seconds: number; }

function threshold(roi: number | null, stat: Stat, level: number, direction: Direction, sustain: number): Threshold {
  const t: Threshold = { kind: "threshold", stat, level_c: level, direction, sustain_frames: sustain };
  if (roi !== null) t.roi = roi;
  return t;
}

export function triggerFromForm(f: TriggerForm): TriggerSpec {
  const start: StartSpec = f.startKind === "manual" ? { kind: "manual" } : f.startKind === "after" ? { kind: "after", after_s: f.afterS }
    : threshold(f.roi, f.stat, f.level, f.direction, f.sustain);
  const end: EndSpec = f.endKind === "manual" ? { kind: "manual" } : f.endKind === "frames" ? { kind: "frames", frames: f.frames }
    : f.endKind === "duration" ? { kind: "duration", seconds: f.seconds } : threshold(f.endRoi ?? f.roi, f.endStat, f.endLevel, f.endDirection, f.sustain);
  return { start, end, pretrigger_s: f.pretrigger, max_seconds: f.maxSeconds };
}

function thresholdText(t: Threshold): string {
  const who = t.roi !== undefined ? `ROI ${t.roi} ${t.stat}` : `first ROI ${t.stat}`;
  return `${who} ${t.direction === "rising" ? "rises above" : "falls below"} ${t.level_c} °C (${t.sustain_frames} frames)`;
}

export function triggerSummary(t: TriggerSpec): string {
  const s = t.start.kind === "manual" ? "start manually" : t.start.kind === "after" ? `start after ${t.start.after_s} s` : `start when ${thresholdText(t.start)}`;
  const e = t.end.kind === "manual" ? "stop manually" : t.end.kind === "frames" ? `stop after ${t.end.frames} frames`
    : t.end.kind === "duration" ? `stop after ${t.end.seconds} s` : `stop when ${thresholdText(t.end)}`;
  const parts = [s, e];
  if (t.pretrigger_s > 0) parts.push(`${t.pretrigger_s} s pre-trigger`);
  parts.push(`cap ${t.max_seconds} s`);
  return parts.join(" · ");
}
