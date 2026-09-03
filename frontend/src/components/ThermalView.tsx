import { VerticalColorBar } from "./VerticalColorBar.tsx";
import { fmtTemp, type Conversion, type Units } from "../lib/units.ts";
import { simplifyPath } from "../lib/geometry.ts";
import { applyFilter, type FilterName } from "../lib/filters.ts";
import { applyMap, plateauMap } from "../lib/agc.ts";
import type { Agc } from "../lib/layout.ts";
const LINEAR_AGC: Agc = { mode: "linear", plateau: 0.5 };
import { HoldBuffer } from "../lib/enhance.ts";
import { subtractReference } from "../lib/reference.ts";
import { applyIsotherm, type Isotherm } from "../lib/isotherm.ts";
import type { Radiometry } from "../lib/emissivity.ts";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as RKeyboardEvent, PointerEvent as RPointerEvent, ReactNode } from "react";
import type { FrameMessage } from "../lib/protocol.ts";
import { countsToCelsius } from "../lib/radiometry.ts";
import { buildLut, mapToRgba, type PaletteName } from "../lib/palette.ts";
import { autoScale, resolveScale, type Range, type ScaleMode } from "../lib/scale.ts";
import { normalizeRect, roiStats, type Roi, type RoiAction, type RoiInput, type RoiStats, visibleRois } from "../lib/roi.ts";
import { clientToImage, hitTest, vertexHit, type Box, type VertexHit } from "../lib/overlay.ts";
import type { Tool } from "../lib/layout.ts";
import { RoiOverlay, type Draft } from "./RoiOverlay.tsx";
import { displaySize, type Zoom } from "../lib/zoom.ts";
import { toCssMatrix3d, type H3 } from "../lib/homography.ts";

export type StatsMap = Map<number, RoiStats>;
const HIT_TOL_PX = 6;
const NO_IDS: number[] = [];
const NO_ROIS: Roi[] = [];
type Pt = { x: number; y: number };

interface Props {
  frame: FrameMessage | null;
  palette: PaletteName;
  scaleMode: ScaleMode;
  manual: Range;
  onScale: (r: Range) => void;
  setManual?: (r: Range) => void; setScaleMode?: (m: ScaleMode) => void;
  rois?: Roi[];
  selected?: number | null;
  selectedIds?: number[];
  tool?: Tool;
  /** "fit" scales the image to the cell (up or down); 1 / 2 are exact pixel factors (scrollable). */
  zoom?: Zoom;
  onRoi?: (a: RoiAction) => void;
  /** Visible-camera element blended over the image (positioned to the image box, below the ROI layer). */
  overlay?: ReactNode;
  overlayStyle?: { opacity: number; scale: number; dx: number; dy: number };
  /** When set, the overlay is warped by this visible→IR homography (normalised coords) instead of scale/shift. */
  overlayH?: H3 | null;
  /** Interactive layer above everything (calibration point picking). */
  topLayer?: ReactNode;
  /** Called with per-ROI statistics every time a frame or the ROI set changes. */
  onStats?: (stats: StatsMap, frame: FrameMessage) => void;
  /** Camera constants for per-ROI emissivity correction (null: ROI emissivity is ignored). */
  rad?: Radiometry | null;
  /** Hot/cold pixel markers inside area ROIs (default on). */
  extremes?: boolean;
  /** Isotherm painted over the palette. */
  isotherm?: Isotherm | null;
  /** The decoded °C field of the frame just drawn (for profiles / histograms). */
  onField?: (snap: { c: Float32Array; w: number; h: number; conv?: Conversion }) => void;
  /** Captured °C field: when set, the image shows (frame − reference) on a diverging scale. */
  reference?: Float32Array | null;
  /** Temporal hold mode; the shown field becomes the per-pixel max/min since the last reset. */
  hold?: "off" | "max" | "min";
  /** Software flip of the displayed image (ROIs stay in sensor coordinates). */
  flipH?: boolean; flipV?: boolean;
  /** Palette mapping: linear, or plateau equalisation of the shown field's histogram. */
  agc?: Agc;
  /** Segmentation range for ROI statistics (null: all pixels count). */
  valid?: Range | null;
  /** Display-only image filter applied before hold / subtraction / AGC. */
  filter?: FilterName;
  /** Units for the hover readout. */
  units?: Units;
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
  if (tool === "ellipse") {  // drag the bounding box corner to corner
    const rx = Math.round(Math.abs(b.x - a.x) / 2), ry = Math.round(Math.abs(b.y - a.y) / 2);
    return rx >= 1 && ry >= 1 ? { kind: "ellipse", cx: Math.round((a.x + b.x) / 2), cy: Math.round((a.y + b.y) / 2), rx, ry } : null;
  }
  if (tool === "line") {
    return a.x !== b.x || a.y !== b.y ? { kind: "line", x0: a.x, y0: a.y, x1: b.x, y1: b.y } : null;
  }
  return null;
}

/** Renders raw counts -> °C -> palette on a canvas, with an ROI overlay layer. Data arrays are never mutated. */
const divergingLut = buildLut("diverging");

export function ThermalView({ frame, palette, scaleMode, manual, onScale, setManual, setScaleMode, rois = NO_ROIS, selected = null, selectedIds = NO_IDS, tool = "select", zoom = "fit", onRoi, overlay, overlayStyle, overlayH, topLayer, onStats, rad = null, extremes = true, isotherm = null, onField, reference = null, hold = "off", flipH = false, flipV = false, agc = LINEAR_AGC, valid = null, filter = "off", units = "C" }: Props) {
  const viewRef = useRef<HTMLDivElement>(null);
  const holdRef = useRef<HoldBuffer | null>(null);
  const freehand = useRef<[number, number][] | null>(null);
  const miniRef = useRef<HTMLCanvasElement>(null);
  const [viewportTick, setViewportTick] = useState(0);
  const panning = useRef<{ cx: number; cy: number; sl: number; st: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const celsiusRef = useRef<Float32Array | null>(null);
  const lutRef = useRef(buildLut(palette));
  const dragStart = useRef<Pt | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; t: number } | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [barRange, setBarRange] = useState<Range | null>(null);
  const [cell, setCell] = useState({ w: 0, h: 0 });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [vertices, setVertices] = useState<[number, number][]>([]); // polygon in progress
  const moving = useRef<{ ids: number[]; last: Pt } | null>(null);
  const editing = useRef<{ id: number; hit: VertexHit } | null>(null);
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
    onField?.({ c, w: header.width, h: header.height, conv: header.kelvin_per_count != null ? { kelvin_per_count: header.kelvin_per_count, kelvin_offset: header.kelvin_offset } : undefined });
    const filtered = filter === "off" ? c : applyFilter(filter, c, header.width, header.height);
    if (hold === "off") holdRef.current = null;
    else if (!holdRef.current || holdRef.current.mode !== hold) holdRef.current = new HoldBuffer(hold);
    const held = holdRef.current ? holdRef.current.push(filtered) : filtered;
    const sub = reference ? subtractReference(held, reference) : null;
    const shownField = sub?.delta ?? held;
    const range = sub?.delta ? sub.range : resolveScale(scaleMode, manual, autoScale(held));
    onScale(range);
    setBarRange(range);
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (canvas.width !== header.width || canvas.height !== header.height) {
      canvas.width = header.width;
      canvas.height = header.height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(header.width, header.height);
    const lutNow = sub?.delta ? divergingLut : lutRef.current;
    if (agc.mode === "plateau" && !sub?.delta) applyMap(shownField, plateauMap(shownField, range, 256, agc.plateau), lutNow, img.data);
    else mapToRgba(shownField, range.min, range.max, lutNow, img.data);
    if (isotherm) applyIsotherm(c, img.data, isotherm);
    ctx.putImageData(img, 0, 0);
    drawMinimap();
  }, [frame, palette, scaleMode, manual.min, manual.max, isotherm, reference, hold, agc.mode, agc.plateau, filter]);

  useEffect(() => {
    const c = celsiusRef.current;
    if (!frame || !c) return;
    const m: StatsMap = new Map();
    for (const r of rois) m.set(r.id, roiStats(c, frame.header.width, frame.header.height, r, rad, valid));
    setStats(m);
    onStats?.(m, frame);
  }, [frame, rois, onStats, rad, valid]);

  function pix(e: { currentTarget: HTMLCanvasElement; clientX: number; clientY: number }): Pt | null {
    if (!hdr) return null;
    const q = clientToImage(e.currentTarget.getBoundingClientRect(), e.clientX, e.clientY, hdr.width, hdr.height);
    if (!q) return q;
    return { x: flipH ? hdr.width - 1 - q.x : q.x, y: flipV ? hdr.height - 1 - q.y : q.y };
  }
  function finishPolygon(pts: [number, number][]) {
    setVertices([]); setDraft(null);
    if (!onRoi) return;
    if (tool === "polyline") { if (pts.length >= 2) onRoi({ type: "add", roi: { kind: "polyline", points: pts } }); return; }
    if (pts.length >= 3) onRoi({ type: "add", roi: { kind: "polygon", points: pts } });
  }
  function onDown(e: RPointerEvent<HTMLCanvasElement>) {
    const p = pix(e);
    if (!p || !onRoi || !hdr) return;
    e.currentTarget.focus();
    if (tool === "spot") { onRoi({ type: "add", roi: { kind: "spot", x: p.x, y: p.y } }); return; }
    if (tool === "rect" || tool === "circle" || tool === "ellipse" || tool === "line") {
      dragStart.current = p;
      setDraft(dragShape(tool, p, p, hdr.width, hdr.height) ?? (tool === "circle" ? { kind: "circle", cx: p.x, cy: p.y, r: 1 } : null));
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* synthetic or already-released pointer */ }
      return;
    }
    if (tool === "polygon" || tool === "polyline") {
      if (e.detail >= 2) return; // the double-click handler closes the shape
      const last = vertices[vertices.length - 1];
      if (last && last[0] === p.x && last[1] === p.y) return;
      const next: [number, number][] = [...vertices, [p.x, p.y]];
      setVertices(next);
      setDraft(next.length >= 2 ? { kind: tool, points: next } : null);
      return;
    }
    if (tool === "freehand") {
      freehand.current = [[p.x, p.y]];
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ }
      return;
    }
    // vertex editing: grabbing a handle of the selected polygon/polyline/line drags that point
    const vtol = box ? Math.max(2, Math.round((HIT_TOL_PX * hdr.width) / box.width)) : HIT_TOL_PX;
    if (selected !== null) {
      const selRoi = visibleRois(rois).find((r) => r.id === selected);
      const vh = selRoi ? vertexHit(selRoi, p.x, p.y, vtol) : null;
      if (vh) { editing.current = { id: selected, hit: vh }; try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ } return; }
    }
    const hit = hitTest(visibleRois(rois), p.x, p.y, HIT_TOL_PX);
    if (hit !== null && e.shiftKey) { onRoi({ type: "toggleSelect", id: hit }); return; }
    if (hit !== null) {
      const inGroup = selectedIds.includes(hit) && selectedIds.length > 1;
      if (!inGroup) onRoi({ type: "select", id: hit });
      moving.current = { ids: inGroup ? selectedIds.slice() : [hit], last: p };
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    } else {
      onRoi({ type: "select", id: null });
      if (zoom !== "fit" && viewRef.current) {
      // empty spot while zoomed in: drag pans the image
      const v = viewRef.current;
      panning.current = { cx: e.clientX, cy: e.clientY, sl: v.scrollLeft, st: v.scrollTop };
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ }
      }
    }
  }
  function onMove(e: RPointerEvent<HTMLCanvasElement>) {
    const pan = panning.current;
    if (pan && viewRef.current) {
      viewRef.current.scrollLeft = pan.sl - (e.clientX - pan.cx);
      viewRef.current.scrollTop = pan.st - (e.clientY - pan.cy);
      return;
    }
    const p = pix(e);
    const c = celsiusRef.current;
    if (!p || !hdr) return setHover(null);
    setHover({ x: p.x, y: p.y, t: c ? c[p.y * hdr.width + p.x] : NaN });
    const ed = editing.current;
    if (ed && onRoi) {
      if (ed.hit.kind === "vertex") onRoi({ type: "setVertex", id: ed.id, index: ed.hit.index, x: p.x, y: p.y });
      else onRoi({ type: "setEndpoint", id: ed.id, end: ed.hit.end, x: p.x, y: p.y });
      return;
    }
    const mv = moving.current;
    if (mv && onRoi) {
      const dx = p.x - mv.last.x, dy = p.y - mv.last.y;
      if (dx || dy) { if (mv.ids.length > 1) onRoi({ type: "moveMany", ids: mv.ids, dx, dy }); else onRoi({ type: "move", id: mv.ids[0], dx, dy }); mv.last = p; }
      return;
    }
    const s = dragStart.current;
    if (s && (tool === "rect" || tool === "circle" || tool === "ellipse" || tool === "line")) setDraft(dragShape(tool, s, p, hdr.width, hdr.height));
    else if ((tool === "polygon" || tool === "polyline") && vertices.length >= 1) setDraft({ kind: tool, points: [...vertices, [p.x, p.y]] });
    else if (tool === "freehand" && freehand.current) {
      const fh = freehand.current, last = fh[fh.length - 1];
      if (Math.abs(last[0] - p.x) + Math.abs(last[1] - p.y) >= 1) { fh.push([p.x, p.y]); setDraft(fh.length >= 2 ? { kind: "polygon", points: fh.slice() } : null); }
    }
  }
  function onUp(e: RPointerEvent<HTMLCanvasElement>) {
    if (panning.current) { panning.current = null; return; }
    if (freehand.current) {
      const pts = simplifyPath(freehand.current, 1.0);
      freehand.current = null; setDraft(null);
      if (pts.length >= 3 && onRoi) onRoi({ type: "add", roi: { kind: "polygon", points: pts } });
      return;
    }
    if (editing.current) { editing.current = null; return; }
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
    if ((tool === "polygon" || tool === "polyline") && vertices.length) {
      if (e.key === "Enter") { e.preventDefault(); finishPolygon(vertices); return; }
      if (e.key === "Escape") { setVertices([]); setDraft(null); return; }
      if (e.key === "Backspace") { e.preventDefault(); const v = vertices.slice(0, -1); setVertices(v); setDraft(v.length >= 2 ? { kind: tool, points: v } : null); return; }
    }
    if (!onRoi || selected === null) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); for (const id of (selectedIds.length ? selectedIds : [selected])) onRoi({ type: "remove", id }); }
    else if (e.key === "Escape") onRoi({ type: "select", id: null });
  }

  function drawMinimap() {
    const mini = miniRef.current, main = canvasRef.current, v = viewRef.current;
    if (!mini || !main || !v || zoom === "fit" || main.width === 0) return;
    const mw = 160, mh = Math.round(mw * main.height / main.width);
    if (mini.width !== mw || mini.height !== mh) { mini.width = mw; mini.height = mh; }
    const mctx = mini.getContext("2d"); if (!mctx) return;
    mctx.imageSmoothingEnabled = true;
    mctx.drawImage(main, 0, 0, mw, mh);
    const cw = main.clientWidth || 1, ch = main.clientHeight || 1;
    const rx = v.scrollLeft / cw, ry = v.scrollTop / ch, rw = Math.min(1, v.clientWidth / cw), rh = Math.min(1, v.clientHeight / ch);
    mctx.strokeStyle = "#ffb000"; mctx.lineWidth = 1.5;
    mctx.strokeRect(rx * mw + 0.5, ry * mh + 0.5, rw * mw - 1, rh * mh - 1);
  }
  function miniJump(e: React.PointerEvent<HTMLCanvasElement>) {
    const mini = miniRef.current, main = canvasRef.current, v = viewRef.current;
    if (!mini || !main || !v || e.buttons === 0) return;
    const r = mini.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    v.scrollLeft = fx * main.clientWidth - v.clientWidth / 2;
    v.scrollTop = fy * main.clientHeight - v.clientHeight / 2;
    setViewportTick((t) => t + 1);
  }
  const size = hdr ? displaySize(hdr.width, hdr.height, cell.w, cell.h, zoom) : null;
  useEffect(() => { drawMinimap(); }, [viewportTick, zoom, size?.width, size?.height]);  // eslint-disable-line react-hooks/exhaustive-deps
  const drawing = tool !== "select";
  const help = (tool === "polygon" || tool === "polyline") && vertices.length ? `${vertices.length} point${vertices.length > 1 ? "s" : ""} · double-click or Enter ${tool === "polygon" ? "closes the polygon" : "ends the line"} · Esc cancels` : null;
  return (
    <div className={`view ${zoom === "fit" ? "" : "scroll"}`} ref={viewRef} onScroll={() => { if (zoom !== "fit") setViewportTick((t) => t + 1); }}>
      <canvas ref={canvasRef} style={{ ...(size ? { width: size.width, height: size.height } : {}), transform: flipH || flipV ? `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})` : undefined }} />
      {overlay && box && (
        <div className="visible-overlay" style={{ left: box.left, top: box.top, width: box.width, height: box.height, opacity: overlayStyle?.opacity ?? 0.5, transform: flipH || flipV ? `scale(${flipH ? -1 : 1}, ${flipV ? -1 : 1})` : undefined }}>
          <div className="visible-overlay-inner" style={overlayH
            ? { transform: toCssMatrix3d(overlayH, box.width, box.height), transformOrigin: "0 0" }
            : { transform: `translate(${overlayStyle?.dx ?? 0}%, ${overlayStyle?.dy ?? 0}%) scale(${overlayStyle?.scale ?? 1})` }}>{overlay}</div>
        </div>
      )}
      {hdr && box && (
        <RoiOverlay box={box} width={hdr.width} height={hdr.height} rois={rois} selected={selected} selectedIds={selectedIds} stats={stats} draft={draft} extremes={extremes} flipH={flipH} flipV={flipV} cursor={drawing ? "crosshair" : selected !== null ? "move" : zoom !== "fit" ? "grab" : "default"}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => { setHover(null); moving.current = null; panning.current = null; editing.current = null; }} onKeyDown={onKey}
          onDoubleClick={() => { if (tool === "polygon" || tool === "polyline") finishPolygon(vertices); }} />
      )}
      {topLayer && box && <div className="top-layer" style={{ left: box.left, top: box.top, width: box.width, height: box.height }}>{topLayer}</div>}
      {hover && (
        <div className="readout">{`x ${hover.x}   y ${hover.y}\nT ${Number.isNaN(hover.t) ? "n/a (not temperature-linear)" : fmtTemp(hover.t, units, hdr && hdr.kelvin_per_count != null ? { kelvin_per_count: hdr.kelvin_per_count, kelvin_offset: hdr.kelvin_offset } : null)}${help ? `\n${help}` : ""}`}</div>
      )}
      {zoom !== "fit" && frame && (
        <canvas ref={miniRef} className="minimap" aria-label="minimap: drag to move the view" title="Minimap: click or drag to move the view"
          onPointerDown={(e) => { (e.currentTarget as HTMLCanvasElement).setPointerCapture(e.pointerId); miniJump(e); }} onPointerMove={miniJump} />
      )}
      {frame && barRange && (
        <VerticalColorBar palette={reference ? "diverging" : palette} range={barRange} units={units}
          conv={hdr && hdr.kelvin_per_count != null ? { kelvin_per_count: hdr.kelvin_per_count, kelvin_offset: hdr.kelvin_offset } : null}
          scaleMode={scaleMode} manual={manual} setManual={reference ? undefined : setManual} setScaleMode={reference ? undefined : setScaleMode} box={box} />
      )}
      {!frame && <div className="readout">no frames</div>}
    </div>
  );
}
