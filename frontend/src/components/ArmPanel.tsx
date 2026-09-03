import { NumberField } from "./NumberField.tsx";
import { useState } from "react";
import { DEFAULT_TRIGGER_FORM, triggerFromForm, triggerSummary, type TriggerForm } from "../lib/trigger.ts";
import { roiLabel, type Roi } from "../lib/roi.ts";
import type { ArmedStatus } from "../lib/api.ts";

interface Props {
  rois: Roi[]; armed: ArmedStatus | null; recording: boolean; disabled: boolean; busy: boolean;
  onArm: (trigger: unknown) => void; onDisarm: () => void; onStartNow: () => void;
}


/** Armed recording: pick a start and an end condition, arm, and let the trigger run the recording. */
export function ArmPanel({ rois, armed, recording, disabled, busy, onArm, onDisarm, onStartNow }: Props) {
  const [f, setF] = useState<TriggerForm>({ ...DEFAULT_TRIGGER_FORM, roi: rois[0]?.id ?? null });
  const [open, setOpen] = useState(false);
  const upd = (patch: Partial<TriggerForm>) => setF({ ...f, ...patch });
  const spec = triggerFromForm(f);
  const area = rois.filter((r) => r.kind !== "line");
  const roiSel = (value: number | null, onChange: (id: number | null) => void, label: string) => (
    <select value={value ?? ""} aria-label={label} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}>
      {area.length === 0 && <option value="">(draw an ROI first)</option>}
      {area.map((r) => <option key={r.id} value={r.id}>{roiLabel(r)}</option>)}
    </select>
  );

  if (armed) {
    const m = armed.machine;
    return (
      <div className="warnbox" role="status" style={{ display: "grid", gap: 6 }}>
        <div><span className="badge rec" style={{ animation: "pulse 1.2s infinite" }}>{recording ? "● TRIGGERED" : "◌ ARMED"}</span> <span className="hint">{triggerSummary(armed.trigger as never)}</span></div>
        <div className="hint">watched value: <b>{armed.watched_value != null ? `${armed.watched_value.toFixed(2)} °C` : "—"}</b>{armed.watched_roi != null ? ` (ROI ${armed.watched_roi})` : ""} · sustain {m.sustain} · buffered {armed.ring_frames} fr{recording ? ` · recorded ${m.frames_recorded} fr` : ""}</div>
        <div className="row">
          {!recording && <button className="primary" disabled={busy} onClick={onStartNow} title="Start the recording now regardless of the start condition">start now</button>}
          <button className="danger" disabled={busy} onClick={onDisarm} title={recording ? "Stop the recording and disarm" : "Disarm without recording"}>{recording ? "■ stop & disarm" : "disarm"}</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="row">
        <button className="secondary" onClick={() => setOpen(!open)} aria-expanded={open} title="Arm a recording that starts and stops on a condition (time, or an ROI temperature threshold)">{open ? "hide trigger" : "trigger…"}</button>
        {open && <button className="primary" disabled={disabled || busy} onClick={() => onArm(spec)} title={triggerSummary(spec)}>◌ Arm</button>}
      </div>
      {open && (
        <div className="kv" style={{ alignItems: "center" }}>
          <span>start</span>
          <span className="v plain" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <select value={f.startKind} aria-label="start condition" onChange={(e) => upd({ startKind: e.target.value as TriggerForm["startKind"] })}>
              <option value="manual">manually</option><option value="after">after a delay</option><option value="threshold">on temperature</option>
            </select>
            {f.startKind === "after" && <><NumberField min={0} step={1} value={f.afterS} style={{ width: 60 }} aria-label="delay s" onChange={(n) => upd({ afterS: n })} /><span className="hint">s</span></>}
            {f.startKind === "threshold" && <>
              {roiSel(f.roi, (roi) => upd({ roi }), "start ROI")}
              <select value={f.stat} aria-label="start statistic" onChange={(e) => upd({ stat: e.target.value as TriggerForm["stat"] })}><option value="max">max</option><option value="mean">mean</option><option value="min">min</option><option value="value">value</option></select>
              <select value={f.direction} aria-label="start direction" onChange={(e) => upd({ direction: e.target.value as TriggerForm["direction"] })}><option value="rising">rises above</option><option value="falling">falls below</option></select>
              <NumberField step={0.5} value={f.level} style={{ width: 64 }} aria-label="start level °C" onChange={(n) => upd({ level: n })} /><span className="hint">°C for</span>
              <NumberField min={1} step={1} value={f.sustain} style={{ width: 48 }} aria-label="sustain frames" onChange={(n) => upd({ sustain: Math.max(1, n) })} /><span className="hint">frames</span>
            </>}
          </span>
          <span>stop</span>
          <span className="v plain" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <select value={f.endKind} aria-label="end condition" onChange={(e) => upd({ endKind: e.target.value as TriggerForm["endKind"] })}>
              <option value="manual">manually</option><option value="duration">after a duration</option><option value="frames">after N frames</option><option value="threshold">on temperature</option>
            </select>
            {f.endKind === "duration" && <><NumberField min={1} step={1} value={f.seconds} style={{ width: 64 }} aria-label="duration s" onChange={(n) => upd({ seconds: n })} /><span className="hint">s</span></>}
            {f.endKind === "frames" && <NumberField min={1} step={1} value={f.frames} style={{ width: 72 }} aria-label="frames" onChange={(n) => upd({ frames: n })} />}
            {f.endKind === "threshold" && <>
              {roiSel(f.endRoi ?? f.roi, (endRoi) => upd({ endRoi }), "end ROI")}
              <select value={f.endStat} aria-label="end statistic" onChange={(e) => upd({ endStat: e.target.value as TriggerForm["stat"] })}><option value="max">max</option><option value="mean">mean</option><option value="min">min</option><option value="value">value</option></select>
              <select value={f.endDirection} aria-label="end direction" onChange={(e) => upd({ endDirection: e.target.value as TriggerForm["direction"] })}><option value="falling">falls below</option><option value="rising">rises above</option></select>
              <NumberField step={0.5} value={f.endLevel} style={{ width: 64 }} aria-label="end level °C" onChange={(n) => upd({ endLevel: n })} /><span className="hint">°C</span>
            </>}
          </span>
          <span>pre-trigger</span>
          <span className="v plain"><NumberField min={0} max={10} step={0.5} value={f.pretrigger} style={{ width: 56 }} aria-label="pre-trigger seconds" onChange={(n) => upd({ pretrigger: n })} /> <span className="hint">s kept from before the start</span></span>
          <span>safety cap</span>
          <span className="v plain"><NumberField min={1} step={60} value={f.maxSeconds} style={{ width: 72 }} aria-label="max seconds" onChange={(n) => upd({ maxSeconds: Math.max(1, n) })} /> <span className="hint">s, always stops</span></span>
          <span className="hint" style={{ gridColumn: "1 / -1" }}>{triggerSummary(spec)}</span>
        </div>
      )}
    </>
  );
}
