import { useEffect, useRef } from "react";
import { buildLut, type PaletteName } from "../lib/palette.ts";
import { niceTicks } from "../lib/plot.ts";
import { convertTemp, UNIT_LABEL, type Conversion, type Units } from "../lib/units.ts";
import type { Range } from "../lib/scale.ts";

/** Vertical colour scale beside the thermal image: max at the top, tick labels in the chosen unit. */
export function VerticalColorBar({ palette, range, units = "C", conv = null }: { palette: PaletteName; range: Range; units?: Units; conv?: Conversion | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = 1; c.height = 256;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const lut = buildLut(palette);
    const img = ctx.createImageData(1, 256);
    for (let i = 0; i < 256; i++) {  // top row = hottest
      const s = (255 - i) * 4, d = i * 4;
      img.data[d] = lut[s]; img.data[d + 1] = lut[s + 1]; img.data[d + 2] = lut[s + 2]; img.data[d + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [palette]);
  const span = range.max - range.min || 1;
  const ticks = niceTicks(range.min, range.max, 5).filter((t) => t >= range.min && t <= range.max);
  const label = units === "counts" ? "counts" : UNIT_LABEL[units];
  return (
    <div className="vbar" aria-hidden="true">
      <canvas ref={ref} className="vbar-gradient" />
      <div className="vbar-ticks">
        {ticks.map((t) => {
          const frac = 1 - (t - range.min) / span;  // 0 at top (max)
          const v = units === "counts" ? convertTemp(t, units, conv) : convertTemp(t, units, conv);
          return <span key={t} style={{ top: `${frac * 100}%` }}>{Number.isFinite(v) ? (units === "counts" ? Math.round(v) : v.toFixed(1)) : "—"}</span>;
        })}
      </div>
      <div className="vbar-unit">{label}</div>
    </div>
  );
}
