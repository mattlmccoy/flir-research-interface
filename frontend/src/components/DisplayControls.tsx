import { PALETTE_NAMES, type PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import { ColorBar } from "./ColorBar.tsx";

interface Props {
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  shown: Range;
}

/** Palette + display-range controls shared by live view and playback. Visualization only. */
export function DisplayControls({ palette, setPalette, scaleMode, setScaleMode, manual, setManual, shown }: Props) {
  return (
    <>
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
