import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as RKeyboardEvent, PointerEvent as RPointerEvent } from "react";
import type { FrameMessage } from "../lib/protocol.ts";
import { countsToCelsius } from "../lib/radiometry.ts";
import { buildLut, mapToRgba, type PaletteName } from "../lib/palette.ts";
import { autoScale, resolveScale, type Range, type ScaleMode } from "../lib/scale.ts";
import { normalizeRect, roiStats, type Roi, type RoiAction, type RoiStats } from "../lib/roi.ts";
import { clientToImage, hitTest, type Box } from "../lib/overlay.ts";
import type { Tool } from "../lib/layout.ts";
import { RoiOverlay, type DraftRect } from "./RoiOverlay.tsx";

export type StatsMap = Map<number, RoiStats>;
const HIT_TOL_PX = 6;
const NO_ROIS: Roi[] = [];

interface Props {
  frame: FrameMessage | null;
  palette: PaletteName;
  scaleMode: ScaleMode;
  manual: Range;
  onScale: (r: Range) => void;
  rois?: Roi[];
  selected?: number | null;
  tool?: Tool;
  onRoi?: (a: RoiAction) => void;
  /** Called with per-ROI statistics every time a frame or the ROI set changes. */
  onStats?: (stats: StatsMap, frame: FrameMessage) => void;
}

/** Renders raw counts -> °C -> palette on a canvas, with an ROI overlay layer. Data arrays are never mutated. */
export function ThermalView({ frame, palette, scaleMode, manual, onScale, rois = NO_ROIS, selected = null, tool = "select", onRoi, onStats }: Props) {
  const viewRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const celsiusRef = useRef<Float32Array | null>(null);
  const lutRef = useRef(buildLut(palette));
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; t: number } | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [draft, setDraft] = useState<DraftRect | null>(null);
  const [stats, setStats] = useState<StatsMap>(new Map());
  const hdr = frame?.header;

  useEffect(() => { lutRef.current = buildLut(palette); }, [palette]);

  // Track where the (letterboxed) image canvas sits inside the view so the overlay matches it.
  useEffect(() => {
    const view = viewRef.current, canvas = canvasRef.current;
    if (!view || !canvas || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const v = view.getBoundingClientRect(), c = canvas.getBoundingClientRect();
      setBox({ left: c.left - v.left, top: c.top - v.top, width: c.width, height: c.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(view); ro.observe(canvas);
    return () => ro.disconnect();
  }, [hdr?.width, hdr?.height]);

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

  useEffect(() => {
    const c = celsiusRef.current;
    if (!frame || !c) return;
    const m: StatsMap = new Map();
    for (const r of rois) m.set(r.id, roiStats(c, frame.header.width, frame.header.height, r));
    setStats(m);
    onStats?.(m, frame);
  }, [frame, rois, onStats]);

  function pix(e: RPointerEvent<HTMLCanvasElement>) {
    if (!hdr) return null;
    return clientToImage(e.currentTarget.getBoundingClientRect(), e.clientX, e.clientY, hdr.width, hdr.height);
  }
  function dragRect(a: { x: number; y: number }, b: { x: number; y: number }) {
    if (!hdr) return null;
    return normalizeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x) + 1, Math.max(a.y, b.y) + 1, hdr.width, hdr.height);
  }
  function onDown(e: RPointerEvent<HTMLCanvasElement>) {
    const p = pix(e);
    if (!p || !onRoi) return;
    e.currentTarget.focus();
    if (tool === "spot") onRoi({ type: "add", roi: { kind: "spot", x: p.x, y: p.y } });
    else if (tool === "rect") { dragStart.current = p; setDraft(dragRect(p, p)); e.currentTarget.setPointerCapture(e.pointerId); }
    else onRoi({ type: "select", id: hitTest(rois, p.x, p.y, HIT_TOL_PX) });
  }
  function onMove(e: RPointerEvent<HTMLCanvasElement>) {
    const p = pix(e);
    const c = celsiusRef.current;
    if (!p || !hdr) return setHover(null);
    setHover({ x: p.x, y: p.y, t: c ? c[p.y * hdr.width + p.x] : NaN });
    if (dragStart.current) setDraft(dragRect(dragStart.current, p));
  }
  function onUp(e: RPointerEvent<HTMLCanvasElement>) {
    const s = dragStart.current;
    if (!s) return;
    dragStart.current = null;
    setDraft(null);
    const p = pix(e);
    const r = p ? dragRect(s, p) : null;
    if (r && onRoi) onRoi({ type: "add", roi: { kind: "rect", ...r } });
  }
  function onKey(e: RKeyboardEvent<HTMLCanvasElement>) {
    if (!onRoi || selected === null) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); onRoi({ type: "remove", id: selected }); }
    else if (e.key === "Escape") onRoi({ type: "select", id: null });
  }

  const cursor = tool === "spot" || tool === "rect" ? "crosshair" : "default";
  return (
    <div className="view" ref={viewRef}>
      <canvas ref={canvasRef} />
      {hdr && box && (
        <RoiOverlay box={box} width={hdr.width} height={hdr.height} rois={rois} selected={selected} stats={stats} draft={draft} cursor={cursor}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => setHover(null)} onKeyDown={onKey} />
      )}
      {hover && (
        <div className="readout">{`x ${hover.x}   y ${hover.y}\nT ${Number.isNaN(hover.t) ? "n/a (not temperature-linear)" : `${hover.t.toFixed(2)} °C`}`}</div>
      )}
      {!frame && <div className="readout">no frames</div>}
    </div>
  );
}
