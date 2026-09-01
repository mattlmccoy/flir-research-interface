import { useEffect, useRef } from "react";
import { buildLut, type PaletteName } from "../lib/palette.ts";
import type { Range } from "../lib/scale.ts";

export function ColorBar({ palette, range }: { palette: PaletteName; range: Range }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.width = 256; c.height = 1;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(256, 1);
    img.data.set(buildLut(palette));
    ctx.putImageData(img, 0, 0);
  }, [palette]);
  return (
    <div className="colorbar">
      <span className="v">{range.min.toFixed(1)}</span>
      <canvas ref={ref} />
      <span className="v">{range.max.toFixed(1)} °C</span>
    </div>
  );
}
