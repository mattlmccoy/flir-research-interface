import { useEffect, useRef } from "react";
import { buildLut, type PaletteName } from "../lib/palette.ts";
import { niceTicks } from "../lib/plot.ts";
import { convertTemp, fmtTemp, UNIT_LABEL, type Conversion, type Units } from "../lib/units.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";

interface Props {
  palette: PaletteName; range: Range; units?: Units; conv?: Conversion | null;
  /** When provided, the bar's endpoints become editable and gain a lock toggle. */
  scaleMode?: ScaleMode; manual?: Range;
  setManual?: (r: Range) => void; setScaleMode?: (m: ScaleMode) => void;
}

/** Vertical colour scale beside the thermal image: max at the top, ticks in the chosen unit,
 * with optional editable min/max and a lock toggle (the same controls as the display panel). */
export function VerticalColorBar({ palette, range, units = "C", conv = null, scaleMode, manual, setManual, setScaleMode }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = 1; c.height = 256;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const lut = buildLut(palette);
    const img = ctx.createImageData(1, 256);
    for (let i = 0; i < 256; i++) { const s = (255 - i) * 4, d = i * 4; img.data[d] = lut[s]; img.data[d + 1] = lut[s + 1]; img.data[d + 2] = lut[s + 2]; img.data[d + 3] = 255; }
    ctx.putImageData(img, 0, 0);
  }, [palette]);

  const span = range.max - range.min || 1;
  const ticks = niceTicks(range.min, range.max, 5).filter((t) => t > range.min + span * 0.06 && t < range.max - span * 0.06);
  const interactive = !!setManual && !!setScaleMode && units !== "counts";
  const disp = scaleMode === "manual" && manual ? manual : range;
  const clamp = (which: "min" | "max", v: number) => {
    const base = scaleMode === "manual" && manual ? manual : { min: Math.round(range.min * 10) / 10, max: Math.round(range.max * 10) / 10 };
    setManual?.({ ...base, [which]: v }); setScaleMode?.("manual");
  };
  const num = (which: "min" | "max") => (
    <input type="number" step={0.5} className="vbar-input" aria-label={`range ${which === "max" ? "maximum" : "minimum"} °C`}
      value={Math.round(disp[which] * 10) / 10} onChange={(e) => clamp(which, Number(e.target.value))} />
  );

  return (
    <div className="vbar" aria-hidden={interactive ? undefined : "true"}>
      {interactive && (
        <button className="vbar-lock secondary" title={scaleMode === "manual" ? "Range locked — click for auto" : "Auto range — click to lock"}
          aria-pressed={scaleMode === "manual"}
          onClick={() => { if (scaleMode === "manual") setScaleMode?.("auto"); else { setManual?.({ min: Math.round(range.min * 10) / 10, max: Math.round(range.max * 10) / 10 }); setScaleMode?.("manual"); } }}>
          {scaleMode === "manual" ? "🔒" : "AUTO"}
        </button>
      )}
      {interactive ? <div className="vbar-end top">{num("max")}</div> : <div className="vbar-end top"><span>{fmtTemp(range.max, units, conv, 1)}</span></div>}
      <div className="vbar-body">
        <canvas ref={ref} className="vbar-gradient" />
        <div className="vbar-ticks">
          {ticks.map((t) => { const frac = 1 - (t - range.min) / span; const v = convertTemp(t, units, conv); return <span key={t} style={{ top: `${frac * 100}%` }}>{Number.isFinite(v) ? (units === "counts" ? Math.round(v) : v.toFixed(1)) : "—"}</span>; })}
        </div>
      </div>
      {interactive ? <div className="vbar-end bottom">{num("min")}<span className="vbar-unit">{UNIT_LABEL[units]}</span></div> : <div className="vbar-end bottom"><span>{units === "counts" ? fmtTemp(range.min, units, conv) : convertTemp(range.min, units, conv).toFixed(1)}</span><span className="vbar-unit">{units === "counts" ? "counts" : UNIT_LABEL[units]}</span></div>}
    </div>
  );
}
