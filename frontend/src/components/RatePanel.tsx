import { roiLabel, type Roi } from "../lib/roi.ts";
import { RATE_WINDOWS, type RateAlarmConfig, type RateAlarmState } from "../lib/rate.ts";

interface Props {
  rois: Roi[];
  rates: Map<number, number | null>;
  cfg: RateAlarmConfig;
  onCfg: (c: RateAlarmConfig) => void;
  /** Latched trip (stays until acknowledged, even after the rate falls back). */
  latched: RateAlarmState | null;
  onAck: () => void;
}

const fmtRate = (r: number | null | undefined) => (r == null || !Number.isFinite(r) ? "—" : `${r >= 0 ? "+" : ""}${r.toFixed(2)}`);

/** Live heating rate per ROI (°C/s, least-squares over a window) and a threshold alarm. */
export function RatePanel({ rois, rates, cfg, onCfg, latched, onAck }: Props) {
  if (rois.length === 0) return null;
  const set = (p: Partial<RateAlarmConfig>) => onCfg({ ...cfg, ...p });
  const name = (id: number | null) => { const r = rois.find((x) => x.id === id); return r ? roiLabel(r) : "ROI"; };
  return (
    <div className="rate-panel">
      <div className="kv" title={`Heating rate: slope of each ROI's ${cfg.stat} over the last ${cfg.windowS} s (°C/s)`}>
        {rois.filter((r) => !r.hidden).map((r) => (
          <span key={r.id} style={{ display: "contents" }}>
            <span>{roiLabel(r)} rate</span>
            <span className="v" style={{ color: cfg.on && (rates.get(r.id) ?? -Infinity) >= cfg.threshold ? "var(--err)" : undefined }}>{fmtRate(rates.get(r.id))} °C/s</span>
          </span>
        ))}
      </div>
      <div className="row" style={{ gap: 4, alignItems: "center", flexWrap: "wrap" }}>
        <label className="hint" title="Alarm when the heating rate reaches the threshold"><input type="checkbox" checked={cfg.on} onChange={(e) => set({ on: e.target.checked })} /> rate alarm</label>
        <select value={String(cfg.roi)} aria-label="ROI watched by the rate alarm" onChange={(e) => set({ roi: e.target.value === "any" ? "any" : Number(e.target.value) })}>
          <option value="any">any ROI</option>
          {rois.map((r) => <option key={r.id} value={r.id}>{roiLabel(r)}</option>)}
        </select>
        <select value={cfg.stat} aria-label="statistic" onChange={(e) => set({ stat: e.target.value as RateAlarmConfig["stat"] })} title="max: the hottest pixel (catches a local hot spot); mean: the region average">
          <option value="max">max</option>
          <option value="mean">mean</option>
        </select>
        <span className="hint">≥</span>
        <input type="number" min={0.1} step={0.5} value={cfg.threshold} aria-label="rate threshold in °C per second" style={{ width: 60 }}
          onChange={(e) => { const n = Number(e.target.value); if (n > 0) set({ threshold: n }); }} />
        <span className="hint">°C/s over</span>
        <select value={String(cfg.windowS)} aria-label="rate window" onChange={(e) => set({ windowS: Number(e.target.value) })} title="Longer windows are steadier but react later">
          {RATE_WINDOWS.map((w) => <option key={w} value={w}>{w} s</option>)}
        </select>
        <label className="hint"><input type="checkbox" checked={cfg.beep} onChange={(e) => set({ beep: e.target.checked })} /> beep</label>
        <label className="hint" title="While recording, add a 'rate alarm' event mark to the run when it trips"><input type="checkbox" checked={cfg.mark} onChange={(e) => set({ mark: e.target.checked })} /> mark run</label>
      </div>
      {latched && (
        <div className="errbox" role="alert">
          <b>Heating-rate alarm</b>: {name(latched.roi)} rose {fmtRate(latched.rate)} °C/s (limit {cfg.threshold} °C/s).
          {" "}This alarm does not stop the RF; turn it off at the RF controller.
          {" "}<button type="button" className="secondary" onClick={onAck}>acknowledge</button>
        </div>
      )}
    </div>
  );
}
