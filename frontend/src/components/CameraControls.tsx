import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";
import { formFromInfo, valuesFromForm, type CameraForm } from "../lib/camera.ts";
import { fmtAny } from "../lib/format.ts";

interface Props {
  info: Record<string, unknown> | null;
  /** True while a recording is in progress: every control is locked (brief §30). */
  locked: boolean;
  onApplied: () => void;
}

type Case = { index: number; low_c?: number | null; high_c?: number | null; enabled?: boolean };

function Num({ label, unit, value, step, min, max, disabled, onChange }: { label: string; unit?: string; value: number | null; step: number; min?: number; max?: number; disabled: boolean; onChange: (v: number) => void }) {
  return (
    <label style={{ display: "contents" }}>
      <span>{label}</span>
      <span className="v plain" style={{ display: "flex", justifyContent: "flex-end", gap: 4, alignItems: "baseline" }}>
        <input type="number" value={value ?? ""} step={step} min={min} max={max} disabled={disabled || value === null} style={{ width: 84 }}
          onChange={(e) => onChange(Number(e.target.value))} />
        {unit && <span className="muted">{unit}</span>}
      </span>
    </label>
  );
}

/** Camera section body: writes real camera nodes; never a host-side calibration (brief §7). */
export function CameraControls({ info, locked, onApplied }: Props) {
  const base = formFromInfo(info ?? {});
  const [form, setForm] = useState<CameraForm>(base);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const baseKey = JSON.stringify(base);
  useEffect(() => { setForm(formFromInfo(info ?? {})); }, [baseKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const pending = valuesFromForm(form, base);
  const dirty = Object.keys(pending).length > 0;
  const cases = ((info?.measurement_cases as Case[] | undefined) ?? []).filter((c) => c.enabled !== false);
  const enums = (info?.enum_options as Record<string, string[]> | undefined) ?? {};
  const dis = locked || busy || !info;

  async function apply() {
    setBusy(true); setErr(null); setOkMsg(null);
    try {
      await api.setParameters(pending);
      setOkMsg(`applied ${Object.keys(pending).join(", ")}`);
      onApplied();
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function nuc() {
    setBusy(true); setErr(null); setOkMsg(null);
    try { await api.nuc(); setOkMsg("NUC requested"); onApplied(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  const set = <K extends keyof CameraForm>(k: K, v: CameraForm[K]) => setForm({ ...form, [k]: v });

  return (
    <>
      {locked && <div className="warnbox">Locked during recording. Stop the recording to change camera parameters.</div>}
      <div className="kv">
        <span>case</span>
        <span className="v plain" style={{ textAlign: "right" }}>
          <select value={form.case_index ?? ""} disabled={dis || form.case_index === null} onChange={(e) => set("case_index", Number(e.target.value))} aria-label="Measurement case">
            {cases.map((c) => <option key={c.index} value={c.index}>{`${fmtAny(c.low_c)}…${fmtAny(c.high_c)} °C`}</option>)}
          </select>
        </span>
        <Num label="emissivity" value={form.emissivity} step={0.01} min={0} max={1} disabled={dis} onChange={(v) => set("emissivity", v)} />
        <Num label="T reflected" unit="°C" value={form.reflected_c} step={0.5} disabled={dis} onChange={(v) => set("reflected_c", v)} />
        <Num label="T atmosphere" unit="°C" value={form.atmospheric_c} step={0.5} disabled={dis} onChange={(v) => set("atmospheric_c", v)} />
        <Num label="distance" unit="m" value={form.distance_m} step={0.1} min={0} disabled={dis} onChange={(v) => set("distance_m", v)} />
        <Num label="humidity" unit="%" value={form.humidity_pct} step={1} min={0} max={100} disabled={dis} onChange={(v) => set("humidity_pct", v)} />
        <span>NUC mode</span>
        <span className="v plain" style={{ textAlign: "right" }}>
          <select value={form.nuc_mode ?? ""} disabled={dis || form.nuc_mode === null} onChange={(e) => set("nuc_mode", e.target.value)} aria-label="NUC mode">
            {(enums.NUCMode ?? (form.nuc_mode ? [form.nuc_mode] : [])).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </span>
        <span>frame rate</span>
        <span className="v plain" style={{ textAlign: "right" }}>
          <select value={form.ir_frame_rate ?? ""} disabled={dis || form.ir_frame_rate === null} onChange={(e) => set("ir_frame_rate", e.target.value)} aria-label="IR frame rate">
            {(enums.IRFrameRate ?? (form.ir_frame_rate ? [form.ir_frame_rate] : [])).map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </span>
        <span>lens</span><span className="v plain">{fmtAny(info?.lens)}</span>
      </div>
      <div className="row">
        <button className="primary" disabled={dis || !dirty} onClick={apply}>{busy ? "…" : "Apply"}</button>
        <button className="secondary" disabled={dis || !dirty} onClick={() => setForm(base)}>Revert</button>
        <button className="secondary" disabled={busy || !info} onClick={nuc} title="Perform a non-uniformity correction now (logged if recording)">NUC now</button>
      </div>
      {okMsg && <div className="hint">{okMsg}</div>}
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
