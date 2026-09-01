import { useEffect, useRef, useState } from "react";
import type { FrameMessage } from "../lib/protocol.ts";
import { countsToCelsius } from "../lib/radiometry.ts";
import { buildLut, mapToRgba, type PaletteName } from "../lib/palette.ts";
import { autoScale, resolveScale, type Range, type ScaleMode } from "../lib/scale.ts";

interface Props {
  frame: FrameMessage | null;
  palette: PaletteName;
  scaleMode: ScaleMode;
  manual: Range;
  onScale: (r: Range) => void;
}

/** Renders raw counts -> °C -> palette on a canvas. Data arrays are never mutated. */
export function ThermalView({ frame, palette, scaleMode, manual, onScale }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const celsiusRef = useRef<Float32Array | null>(null);
  const lutRef = useRef(buildLut(palette));
  const [hover, setHover] = useState<{ x: number; y: number; t: number } | null>(null);

  useEffect(() => { lutRef.current = buildLut(palette); }, [palette]);

  useEffect(() => {
    if (!frame) return;
    const { header, counts } = frame;
    const c = countsToCelsius(counts, header.kelvin_per_count, header.kelvin_offset);
    celsiusRef.current = c;
    const range = resolveScale(scaleMode, manual, autoScale(c));
    onScale(range);
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (canvas.width !== header.width || canvas.height !== header.height) {
      canvas.width = header.width;
      canvas.height = header.height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(header.width, header.height);
    mapToRgba(c, range.min, range.max, lutRef.current, img.data);
    ctx.putImageData(img, 0, 0);
  }, [frame, palette, scaleMode, manual.min, manual.max]);

  function onMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    const c = celsiusRef.current;
    if (!canvas || !c || !frame) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - rect.left) / rect.width) * canvas.width);
    const y = Math.floor(((e.clientY - rect.top) / rect.height) * canvas.height);
    if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) return setHover(null);
    setHover({ x, y, t: c[y * canvas.width + x] });
  }

  return (
    <div className="view">
      <canvas ref={canvasRef} onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      {hover && (
        <div className="readout">
          x: {hover.x}&nbsp; y: {hover.y}<br />
          T: {Number.isNaN(hover.t) ? "n/a (not temperature-linear)" : `${hover.t.toFixed(2)} °C`}
        </div>
      )}
      {!frame && <div className="readout">no frames</div>}
    </div>
  );
}
