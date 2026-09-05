import { NumberField } from "./NumberField.tsx";
import { UNITS, UNIT_LABEL, type Conversion, type Units } from "../lib/units.ts";
import type { FilterName } from "../lib/filters.ts";
import type { Agc } from "../lib/layout.ts";
import { DEFAULT_ISOTHERM, type Isotherm } from "../lib/isotherm.ts";
import { PALETTE_NAMES, type PaletteName, PALETTE_NOTES } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import { ColorBar } from "./ColorBar.tsx";

interface Props {
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  shown: Range;
  /** Isotherm painting (optional: omitted hides the controls). */
  isotherm?: Isotherm; setIsotherm?: (iso: Isotherm) => void;
  /** Reference-frame subtraction: capture the current frame, show frame − reference. */
  hasReference?: boolean; onSetReference?: () => void; onClearReference?: () => void;
  /** Save the image with its ROI overlay as a PNG (Research Studio "save image"). */
  onSnapshot?: () => void;
  /** Lock the range to the selected ROI's min/max (ResearchIR "scale limits from active ROI"). */
  onRangeFromRoi?: (() => void) | null;
  hold?: "off" | "max" | "min"; setHold?: (h: "off" | "max" | "min") => void;
  flipH?: boolean; flipV?: boolean; setFlip?: (h: boolean, v: boolean) => void;
  /** Pixels at/beyond the camera's calibrated case limits in the current frame. */
  saturation?: { low: number; high: number; lowC: number; highC: number } | null;
  agc?: Agc; setAgc?: (a: Agc) => void;
  segment?: { on: boolean; min: number; max: number }; setSegment?: (s: { on: boolean; min: number; max: number }) => void;
  filter?: FilterName; setFilter?: (f: FilterName) => void;
  units?: Units; setUnits?: (u: Units) => void; conv?: Conversion | null;
}

/** Palette + display-range controls shared by live view and playback. Visualization only. */
export function DisplayControls({ palette, setPalette, scaleMode, setScaleMode, manual, setManual, shown, isotherm, setIsotherm, hasReference, onSetReference, onClearReference, onSnapshot, onRangeFromRoi, hold = "off", setHold, flipH = false, flipV = false, setFlip, saturation, agc, setAgc, segment, setSegment, filter = "off", setFilter, units = "C", setUnits, conv = null }: Props) {
  const iso = isotherm ?? DEFAULT_ISOTHERM;
  const upd = (patch: Partial<Isotherm>) => setIsotherm?.({ ...iso, ...patch });
  const isoRow = setIsotherm && (
    <div className="row" aria-label="isotherm" title="Paint every pixel above / below / between the limits a solid color on top of the palette (visualisation only; nothing is written to the data)">
      <span className="hint">isotherm</span>
      <select value={iso.mode} onChange={(e) => upd({ mode: e.target.value as Isotherm["mode"] })} aria-label="isotherm mode">
        <option value="off">off</option><option value="above">above</option><option value="below">below</option><option value="between">between</option>
      </select>
      {iso.mode !== "off" && <NumberField step={0.5} value={iso.lo} style={{ width: 64 }} aria-label={iso.mode === "between" ? "isotherm low limit °C" : "isotherm limit °C"} onChange={(n) => upd({ lo: n })} />}
      {iso.mode === "between" && <NumberField step={0.5} value={iso.hi} style={{ width: 64 }} aria-label="isotherm high limit °C" onChange={(n) => upd({ hi: n })} />}
      {iso.mode !== "off" && <span className="hint">°C</span>}
      {iso.mode !== "off" && <input type="color" value={iso.color} aria-label="isotherm color" onChange={(e) => upd({ color: e.target.value })} />}
    </div>
  );
  const refRow = onSetReference && (
    <div className="row" aria-label="reference frame" title="Capture the current frame as the reference; the image then shows each pixel's change from it on a blue–neutral–red scale (display only: ROI values, plots and recordings stay absolute)">
      <span className="hint">reference</span>
      <button className="secondary" onClick={onSetReference}>{hasReference ? "re-capture" : "set from this frame"}</button>
      {hasReference && <><span className="badge manual">frame − reference</span><button className="secondary" onClick={onClearReference}>clear</button></>}
    </div>
  );
  return (
    <>
      {setUnits && (
        <div className="row" aria-label="units">
          <span className="hint">units</span>
          <select value={units} onChange={(e) => setUnits(e.target.value as Units)} aria-label="display units" title="Units for every temperature readout (values, ROI rows, color bar). Inputs such as range limits stay in °C. Counts = the camera's raw 16-bit value.">
            {UNITS.map((u) => <option key={u} value={u}>{UNIT_LABEL[u]}</option>)}
          </select>
        </div>
      )}
      {onSnapshot && (
        <div className="row">
          <button className="secondary" onClick={onSnapshot} title="Download the thermal image with its ROIs, palette and a caption line as a PNG at native resolution">⤓ save image</button>
        </div>
      )}
      {(setHold || setFlip || onRangeFromRoi !== undefined) && (
        <div className="row" aria-label="enhancement">
          {onRangeFromRoi !== undefined && <button className="secondary" disabled={!onRangeFromRoi} onClick={() => onRangeFromRoi?.()} title="Lock the color range to the selected ROI's min and max (select an area ROI first)">range ← ROI</button>}
          {setHold && (
            <select value={hold} onChange={(e) => setHold(e.target.value as "off" | "max" | "min")} aria-label="temporal hold" title="Show the hottest (or coldest) value each pixel has reached since you switched this on — a peak-temperature map. Measurements stay live.">
              <option value="off">live frame</option><option value="max">max hold</option><option value="min">min hold</option>
            </select>
          )}
          {setHold && hold !== "off" && <button className="secondary" onClick={() => { setHold("off"); setTimeout(() => setHold(hold), 0); }} title="Restart the hold from the next frame">reset</button>}
          {setFilter && (
            <select value={filter} onChange={(e) => setFilter(e.target.value as FilterName)} aria-label="image filter" title="Display-only smoothing: box blur 3×3 / 5×5 or a 3×3 median (removes single-pixel spikes). Measurements use the unfiltered pixels.">
              <option value="off">no filter</option><option value="blur3">blur 3×3</option><option value="blur5">blur 5×5</option><option value="median3">median 3×3</option>
            </select>
          )}
          {setFlip && <button className="secondary" aria-pressed={flipH} onClick={() => setFlip(!flipH, flipV)} title="Mirror the image left–right (display only)">⇋ H</button>}
          {setFlip && <button className="secondary" aria-pressed={flipV} onClick={() => setFlip(flipH, !flipV)} title="Mirror the image top–bottom (display only)">⇅ V</button>}
        </div>
      )}
      {setAgc && agc && (
        <div className="row" aria-label="AGC" title="How the palette is spread over the range. Linear: even. Plateau equalisation: bands where most pixels sit get more colors (ResearchIR's PE); the color bar is then non-linear.">
          <span className="hint">AGC</span>
          <select value={agc.mode} onChange={(e) => setAgc({ ...agc, mode: e.target.value as Agc["mode"] })} aria-label="AGC mode"><option value="linear">linear</option><option value="plateau">plateau equalisation</option></select>
          {agc.mode === "plateau" && <input type="range" min={0} max={1} step={0.05} value={agc.plateau} aria-label="plateau strength" style={{ width: 110 }} onChange={(e) => setAgc({ ...agc, plateau: Number(e.target.value) })} />}
          {agc.mode === "plateau" && <span className="hint">{Math.round(agc.plateau * 100)} %</span>}
        </div>
      )}
      {setSegment && segment && (
        <div className="row" aria-label="segmentation" title="Only pixels within this temperature range count in ROI statistics (ResearchIR segmentation); excluded pixels are reported per ROI. Recording and exports are unaffected.">
          <label className="hint"><input type="checkbox" checked={segment.on} onChange={(e) => setSegment({ ...segment, on: e.target.checked })} /> stats only within</label>
          <NumberField step={0.5} value={segment.min} style={{ width: 64 }} aria-label="segmentation min °C" disabled={!segment.on} onChange={(n) => setSegment({ ...segment, min: n })} />
          <span className="hint">to</span>
          <NumberField step={0.5} value={segment.max} style={{ width: 64 }} aria-label="segmentation max °C" disabled={!segment.on} onChange={(n) => setSegment({ ...segment, max: n })} />
          <span className="hint">°C</span>
        </div>
      )}
      {saturation && (saturation.low > 0 || saturation.high > 0) && (
        <div className="warnbox">{saturation.high > 0 ? `${saturation.high} px at/above the case limit (${saturation.highC.toFixed(0)} °C)` : ""}{saturation.high > 0 && saturation.low > 0 ? " · " : ""}{saturation.low > 0 ? `${saturation.low} px at/below ${saturation.lowC.toFixed(0)} °C` : ""} — outside the calibrated range; switch measurement case.</div>
      )}
      {refRow}
      {isoRow}
      <div className="row">
        <select value={palette} onChange={(e) => setPalette(e.target.value as PaletteName)} title={PALETTE_NOTES[palette]}>
          {PALETTE_NAMES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <span className={`badge ${scaleMode}`}>{scaleMode === "auto" ? "AUTO" : "LOCKED"}</span>
        <button className="secondary" onClick={() => {
          if (scaleMode === "auto") { setManual({ min: Math.round(shown.min * 10) / 10, max: Math.round(shown.max * 10) / 10 }); setScaleMode("manual"); }
          else setScaleMode("auto");
        }}>{scaleMode === "auto" ? "Lock range" : "Auto range"}</button>
      </div>
      <div className="hint">{PALETTE_NOTES[palette]}</div>
      <div className="row">
        <label>min <NumberField step={0.5} aria-label="range minimum °C" value={scaleMode === "manual" ? manual.min : Math.round(shown.min * 10) / 10}
          onChange={(n) => { const base = scaleMode === "manual" ? manual : { min: shown.min, max: Math.round(shown.max * 10) / 10 }; setManual({ ...base, min: n }); setScaleMode("manual"); }} /> °C</label>
        <label>max <NumberField step={0.5} aria-label="range maximum °C" value={scaleMode === "manual" ? manual.max : Math.round(shown.max * 10) / 10}
          onChange={(n) => { const base = scaleMode === "manual" ? manual : { min: Math.round(shown.min * 10) / 10, max: shown.max }; setManual({ ...base, max: n }); setScaleMode("manual"); }} /> °C</label>
      </div>
      <div className="hint">{scaleMode === "auto" ? "Auto: the range follows each frame's min and max. Type a limit to lock it." : "Locked: colors stay fixed at these limits; values outside clip. \"Auto range\" returns to per-frame scaling."}</div>
      <ColorBar palette={palette} range={shown} units={units} conv={conv} />
    </>
  );
}
