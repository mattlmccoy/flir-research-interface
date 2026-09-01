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
      <h3>Display (visualization only)</h3>
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
      {scaleMode === "manual" && (
        <div className="row">
          <label>min <input type="number" value={manual.min} onChange={(e) => setManual({ ...manual, min: Number(e.target.value) })} /></label>
          <label>max <input type="number" value={manual.max} onChange={(e) => setManual({ ...manual, max: Number(e.target.value) })} /></label>
        </div>
      )}
      <ColorBar palette={palette} range={shown} />
    </>
  );
}
