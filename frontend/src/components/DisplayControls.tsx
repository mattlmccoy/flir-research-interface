import { DEFAULT_ISOTHERM, type Isotherm } from "../lib/isotherm.ts";
import { PALETTE_NAMES, type PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import { ColorBar } from "./ColorBar.tsx";

interface Props {
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  shown: Range;
  /** Isotherm painting (optional: omitted hides the controls). */
  isotherm?: Isotherm; setIsotherm?: (iso: Isotherm) => void;
}

/** Palette + display-range controls shared by live view and playback. Visualization only. */
export function DisplayControls({ palette, setPalette, scaleMode, setScaleMode, manual, setManual, shown, isotherm, setIsotherm }: Props) {
  const iso = isotherm ?? DEFAULT_ISOTHERM;
  const upd = (patch: Partial<Isotherm>) => setIsotherm?.({ ...iso, ...patch });
  const isoRow = setIsotherm && (
    <div className="row" aria-label="isotherm" title="Paint every pixel above / below / between the limits a solid colour on top of the palette (visualisation only; nothing is written to the data)">
      <span className="hint">isotherm</span>
      <select value={iso.mode} onChange={(e) => upd({ mode: e.target.value as Isotherm["mode"] })} aria-label="isotherm mode">
        <option value="off">off</option><option value="above">above</option><option value="below">below</option><option value="between">between</option>
      </select>
      {iso.mode !== "off" && <input type="number" step={0.5} value={iso.lo} style={{ width: 64 }} aria-label={iso.mode === "between" ? "isotherm low limit °C" : "isotherm limit °C"} onChange={(e) => upd({ lo: Number(e.target.value) })} />}
      {iso.mode === "between" && <input type="number" step={0.5} value={iso.hi} style={{ width: 64 }} aria-label="isotherm high limit °C" onChange={(e) => upd({ hi: Number(e.target.value) })} />}
      {iso.mode !== "off" && <span className="hint">°C</span>}
      {iso.mode !== "off" && <input type="color" value={iso.color} aria-label="isotherm colour" onChange={(e) => upd({ color: e.target.value })} />}
    </div>
  );
  return (
    <>
      {isoRow}
      <div className="row">
        <select value={palette} onChange={(e) => setPalette(e.target.value as PaletteName)}>
          {PALETTE_NAMES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className={`badge ${scaleMode}`}>{scaleMode === "auto" ? "AUTO" : "LOCKED"}</span>
        <button className="secondary" onClick={() => {
          if (scaleMode === "auto") { setManual({ min: Math.round(shown.min * 10) / 10, max: Math.round(shown.max * 10) / 10 }); setScaleMode("manual"); }
          else setScaleMode("auto");
        }}>{scaleMode === "auto" ? "Lock range" : "Auto range"}</button>
      </div>
      <div className="row">
        <label>min <input type="number" step={0.5} aria-label="range minimum °C" value={scaleMode === "manual" ? manual.min : Math.round(shown.min * 10) / 10}
          onChange={(e) => { const base = scaleMode === "manual" ? manual : { min: shown.min, max: Math.round(shown.max * 10) / 10 }; setManual({ ...base, min: Number(e.target.value) }); setScaleMode("manual"); }} /> °C</label>
        <label>max <input type="number" step={0.5} aria-label="range maximum °C" value={scaleMode === "manual" ? manual.max : Math.round(shown.max * 10) / 10}
          onChange={(e) => { const base = scaleMode === "manual" ? manual : { min: Math.round(shown.min * 10) / 10, max: shown.max }; setManual({ ...base, max: Number(e.target.value) }); setScaleMode("manual"); }} /> °C</label>
      </div>
      <div className="hint">{scaleMode === "auto" ? "Auto: the range follows each frame's min and max. Type a limit to lock it." : "Locked: colours stay fixed at these limits; values outside clip. \"Auto range\" returns to per-frame scaling."}</div>
      <ColorBar palette={palette} range={shown} />
    </>
  );
}
