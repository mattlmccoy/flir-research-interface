import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as RKeyboardEvent, PointerEvent as RPointerEvent } from "react";
import type { FrameMessage } from "../lib/protocol.ts";
import { countsToCelsius } from "../lib/radiometry.ts";
import { buildLut, mapToRgba, type PaletteName } from "../lib/palette.ts";
import { autoScale, resolveScale, type Range, type ScaleMode } from "../lib/scale.ts";
import { normalizeRect, roiStats, type Roi, type RoiAction, type RoiInput, type RoiStats } from "../lib/roi.ts";
import { clientToImage, hitTest, type Box } from "../lib/overlay.ts";
import type { Tool } from "../lib/layout.ts";
import { RoiOverlay, type Draft } from "./RoiOverlay.tsx";
import { displaySize, type Zoom } from "../lib/zoom.ts";

export type StatsMap = Map<number, RoiStats>;
const HIT_TOL_PX = 6;
const NO_ROIS: Roi[] = [];
type Pt = { x: number; y: number };

interface Props {
  frame: FrameMessage | null;
  palette: PaletteName;
  scaleMode: ScaleMode;
  manual: Range;
  onScale: (r: Range) => void;
  rois?: Roi[];
  selected?: number | null;
  tool?: Tool;
  /** "fit" scales the image to the cell (up or down); 1 / 2 are exact pixel factors (scrollable). */
  zoom?: Zoom;
  onRoi?: (a: RoiAction) => void;
  /** Called with per-ROI statistics every time a frame or the ROI set changes. */
  onStats?: (stats: StatsMap, frame: FrameMessage) => void;
}

/** The shape a drag from `a` to `b` produces for the active tool (null when degenerate). */
export function dragShape(tool: Tool, a: Pt, b: Pt, w: number, h: number): RoiInput | null {
  if (tool === "rect") {
    const r = normalizeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x) + 1, Math.max(a.y, b.y) + 1, w, h);
    return r ? { kind: "rect", ...r } : null;
  }
  if (tool === "circle") {
    const r = Math.round(Math.hypot(b.x - a.x, b.y - a.y));
    return r >= 1 ? { kind: "circle", cx: a.x, cy: a.y, r } : null;
  }
  if (tool === "line") {
    return a.x !== b.x || a.y !== b.y ? { kind: "line", x0: a.x, y0: a.y, x1: b.x, y1: b.y } : null;
  }
  return null;
}

/** Renders raw counts -> °C -> palette on a canvas, with an ROI overlay layer. Data arrays are never mutated. */
export function ThermalView({ frame, palette, scaleMode, manual, onScale, rois = NO_ROIS, selected = null, tool = "select", zoom = "fit", onRoi, onStats }: Props) {
  const viewRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const celsiusRef = useRef<Float32Array | null>(null);
  const lutRef = useRef(buildLut(palette));
  const dragStart = useRef<Pt | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; t: number } | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [cell, setCell] = useState({ w: 0, h: 0 });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [vertices, setVertices] = useState<[number, number][]>([]); // polygon in progress
  const moving = useRef<{ id: number; last: Pt } | null>(null);
  const [stats, setStats] = useState<StatsMap>(new Map());
  const hdr = frame?.header;

  useEffect(() => { lutRef.current = buildLut(palette); }, [palette]);
  useEffect(() => { setVertices([]); setDraft(null); dragStart.current = null; }, [tool]);

  // Track where the (letterboxed) image canvas sits inside the view so the overlay matches it.
  useEffect(() => {
    const view = viewRef.current, canvas = canvasRef.current;
    if (!view || !canvas || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const v = view.getBoundingClientRect(), c = canvas.getBoundingClientRect();
      setCell({ w: view.clientWidth, h: view.clientHeight });
      setBox({ left: c.left - v.left + view.scrollLeft, top: c.top - v.top + view.scrollTop, width: c.width, height: c.height });
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

  function pix(e: { currentTarget: HTMLCanvasElement; clientX: number; clientY: number }): Pt | null {
    if (!hdr) return null;
    return clientToImage(e.currentTarget.getBoundingClientRect(), e.clientX, e.clientY, hdr.width, hdr.height);
  }
  function finishPolygon(pts: [number, number][]) {
    setVertices([]); setDraft(null);
    if (pts.length >= 3 && onRoi) onRoi({ type: "add", roi: { kind: "polygon", points: pts } });
  }
  function onDown(e: RPointerEvent<HTMLCanvasElement>) {
    const p = pix(e);
    if (!p || !onRoi || !hdr) return;
    e.currentTarget.focus();
    if (tool === "spot") { onRoi({ type: "add", roi: { kind: "spot", x: p.x, y: p.y } }); return; }
    if (tool === "rect" || tool === "circle" || tool === "line") {
      dragStart.current = p;
      setDraft(dragShape(tool, p, p, hdr.width, hdr.height) ?? (tool === "circle" ? { kind: "circle", cx: p.x, cy: p.y, r: 1 } : null));
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* synthetic or already-released pointer */ }
      return;
    }
    if (tool === "polygon") {
      if (e.detail >= 2) return; // the double-click handler closes the shape
      const last = vertices[vertices.length - 1];
      if (last && last[0] === p.x && last[1] === p.y) return;
      const next: [number, number][] = [...vertices, [p.x, p.y]];
      setVertices(next);
      setDraft(next.length >= 2 ? { kind: "polygon", points: next } : null);
      return;
    }
    const hit = hitTest(rois, p.x, p.y, HIT_TOL_PX);
    onRoi({ type: "select", id: hit });
    if (hit !== null) { moving.current = { id: hit, last: p }; try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ } }
  }
  function onMove(e: RPointerEvent<HTMLCanvasElement>) {
    const p = pix(e);
    const c = celsiusRef.current;
    if (!p || !hdr) return setHover(null);
    setHover({ x: p.x, y: p.y, t: c ? c[p.y * hdr.width + p.x] : NaN });
    const mv = moving.current;
    if (mv && onRoi) {
      const dx = p.x - mv.last.x, dy = p.y - mv.last.y;
      if (dx || dy) { onRoi({ type: "move", id: mv.id, dx, dy }); mv.last = p; }
      return;
    }
    const s = dragStart.current;
    if (s && (tool === "rect" || tool === "circle" || tool === "line")) setDraft(dragShape(tool, s, p, hdr.width, hdr.height));
    else if (tool === "polygon" && vertices.length >= 1) setDraft({ kind: "polygon", points: [...vertices, [p.x, p.y]] });
  }
  function onUp(e: RPointerEvent<HTMLCanvasElement>) {
    if (moving.current) { moving.current = null; return; }
    const s = dragStart.current;
    if (!s || !hdr) return;
    dragStart.current = null;
    setDraft(null);
    const p = pix(e);
    const shape = p ? dragShape(tool, s, p, hdr.width, hdr.height) : null;
    if (shape && onRoi) onRoi({ type: "add", roi: shape });
  }
  function onKey(e: RKeyboardEvent<HTMLCanvasElement>) {
    if (tool === "polygon" && vertices.length) {
      if (e.key === "Enter") { e.preventDefault(); finishPolygon(vertices); return; }
      if (e.key === "Escape") { setVertices([]); setDraft(null); return; }
      if (e.key === "Backspace") { e.preventDefault(); const v = vertices.slice(0, -1); setVertices(v); setDraft(v.length >= 2 ? { kind: "polygon", points: v } : null); return; }
    }
    if (!onRoi || selected === null) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); onRoi({ type: "remove", id: selected }); }
    else if (e.key === "Escape") onRoi({ type: "select", id: null });
  }

  const size = hdr ? displaySize(hdr.width, hdr.height, cell.w, cell.h, zoom) : null;
  const drawing = tool !== "select";
  const help = tool === "polygon" && vertices.length ? `${vertices.length} point${vertices.length > 1 ? "s" : ""} · double-click or Enter closes the polygon · Esc cancels` : null;
  return (
    <div className={`view ${zoom === "fit" ? "" : "scroll"}`} ref={viewRef}>
      <canvas ref={canvasRef} style={size ? { width: size.width, height: size.height } : undefined} />
      {hdr && box && (
        <RoiOverlay box={box} width={hdr.width} height={hdr.height} rois={rois} selected={selected} stats={stats} draft={draft} cursor={drawing ? "crosshair" : selected !== null ? "move" : "default"}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => { setHover(null); moving.current = null; }} onKeyDown={onKey}
          onDoubleClick={() => { if (tool === "polygon") finishPolygon(vertices); }} />
      )}
      {hover && (
        <div className="readout">{`x ${hover.x}   y ${hover.y}\nT ${Number.isNaN(hover.t) ? "n/a (not temperature-linear)" : `${hover.t.toFixed(2)} °C`}${help ? `\n${help}` : ""}`}</div>
      )}
      {!frame && <div className="readout">no frames</div>}
    </div>
  );
}
