import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent as RKeyboardEvent, MouseEvent as RMouseEvent, PointerEvent as RPointerEvent } from "react";
import { roiLabel, type Roi, type RoiInput, type RoiStats } from "../lib/roi.ts";
import { roiColor, type Box, vertexHandles } from "../lib/overlay.ts";
import { layoutLabels, type LabelBox } from "../lib/labels.ts";
import { type ChipRect, hitChip, loadOffsets, type Offsets, saveOffsets } from "../lib/labelDrag.ts";

const storage = (() => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; } })();

/** In-progress shape while the pointer is down / vertices are being placed. */
export type Draft = RoiInput;

type PE = RPointerEvent<HTMLCanvasElement>;
interface Props {
  box: Box; width: number; height: number;
  rois: Roi[]; selected: number | null; selectedIds?: number[]; stats: Map<number, RoiStats>; draft: Draft | null;
  /** Draw ▲ at the hottest and ▽ at the coldest pixel of every area ROI (default on). */
  extremes?: boolean;
  /** Mirror the geometry to match a flipped image; labels stay readable. */
  flipH?: boolean; flipV?: boolean;
  cursor: string;
  /** Hide all shapes + labels (a view toggle); the canvas stays for pointer interaction. */
  hidden?: boolean;
  /** Active drawing tool; label dragging is only armed on the "select" tool. */
  tool?: string;
  /** localStorage scope for label-position nudges (live vs a specific experiment). */
  labelScope?: string;
  onPointerDown: (e: PE) => void; onPointerMove: (e: PE) => void; onPointerUp: (e: PE) => void;
  onPointerLeave: () => void; onKeyDown: (e: RKeyboardEvent<HTMLCanvasElement>) => void;
  onDoubleClick?: (e: RMouseEvent<HTMLCanvasElement>) => void;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#ffffff";
}
/** Resolves "var(--x)" to its value; plain colours pass through. */
function resolve(color: string): string {
  const m = /^var\((--[a-z0-9-]+)\)$/i.exec(color);
  return m ? cssVar(m[1]) : color;
}
const FILL_ALPHA = 0.14;

/** The per-context base transform (device pixel ratio only, no flip), set once per draw. */
const BASE = new WeakMap<CanvasRenderingContext2D, DOMMatrix>();

// --- ROI label chips: solid, legible, collision-resolved -------------------------------------
const PAD = 5, DOTR = 3, SEGGAP = 7, LINE1_H = 18, LINE2_H = 13;
const NAME_COLOR = "#e8eaed", VALUE_COLOR = "#ffffff", DIM_COLOR = "#9aa0a6";
const CHIP_BG = "rgba(12,14,18,0.9)", CHIP_BORDER = "rgba(255,255,255,0.14)";

/** A chip's content: name + live mean on line 1, and (for area ROIs) min…max always on line 2. */
interface ChipContent { name: string; value: string; range: string | null; }

function labelContent(r: Roi, s: RoiStats | undefined): ChipContent {
  const name = roiLabel(r);
  if (!s || s.n === 0 || s.mean === null) return { name, value: s ? "n/a" : "", range: null };
  const range = r.kind !== "spot" && s.min != null && s.max != null
    ? `${s.min.toFixed(1)}…${s.max.toFixed(1)}` : null;
  return { name, value: `${s.mean.toFixed(1)}°`, range };
}

const nameX = PAD + DOTR * 2 + 5; // where text starts, right of the colour dot

function chipSize(ctx: CanvasRenderingContext2D, c: ChipContent): { w: number; h: number } {
  const line1 = nameX + ctx.measureText(c.name).width + (c.value ? SEGGAP + ctx.measureText(c.value).width : 0);
  const line2 = c.range ? nameX + ctx.measureText(c.range).width : 0;
  return { w: Math.max(line1, line2) + PAD, h: LINE1_H + (c.range ? LINE2_H : 0) };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  if (typeof ctx.roundRect === "function") { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); return; }
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

/** Dark rounded chip: colour dot + name + mean on line 1, min…max on line 2. */
function drawChip(ctx: CanvasRenderingContext2D, x: number, y: number, c: ChipContent, dotColor: string): void {
  const { w, h } = chipSize(ctx, c);
  roundRect(ctx, x, y, w, h, 4);
  ctx.fillStyle = CHIP_BG; ctx.fill();
  ctx.strokeStyle = CHIP_BORDER; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.stroke();
  ctx.beginPath(); ctx.arc(x + PAD + DOTR, y + LINE1_H / 2, DOTR, 0, Math.PI * 2); ctx.fillStyle = dotColor; ctx.fill();
  const ty = y + LINE1_H / 2 + 4;
  ctx.fillStyle = NAME_COLOR; ctx.fillText(c.name, x + nameX, ty);
  if (c.value) { ctx.fillStyle = VALUE_COLOR; ctx.fillText(c.value, x + nameX + ctx.measureText(c.name).width + SEGGAP, ty); }
  if (c.range) { ctx.fillStyle = DIM_COLOR; ctx.fillText(c.range, x + nameX, y + LINE1_H + LINE2_H / 2 + 2); }
}

/** Strokes one shape in canvas pixels (filled shapes get a translucent tint); returns where its label goes. */
function drawShape(ctx: CanvasRenderingContext2D, r: RoiInput, sx: number, sy: number, fill: boolean): [number, number] {
  const tint = () => { if (!fill) return; ctx.save(); ctx.globalAlpha = FILL_ALPHA; ctx.fillStyle = ctx.strokeStyle; ctx.fill(); ctx.restore(); };
  switch (r.kind) {
    case "rect": {
      const x = r.x0 * sx, y = r.y0 * sy, w = (r.x1 - r.x0) * sx, h = (r.y1 - r.y0) * sy;
      ctx.beginPath(); ctx.rect(x + 0.5, y + 0.5, w, h); tint(); ctx.stroke();
      return [x, y - 3];
    }
    case "spot": {
      const x = (r.x + 0.5) * sx, y = (r.y + 0.5) * sy;
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 11, y); ctx.lineTo(x + 11, y); ctx.moveTo(x, y - 11); ctx.lineTo(x, y + 11); ctx.stroke();
      return [x + 10, y - 8];
    }
    case "ellipse": {
      const x = (r.cx + 0.5) * sx, y = (r.cy + 0.5) * sy;
      ctx.beginPath(); ctx.ellipse(x, y, r.rx * sx, r.ry * sy, 0, 0, Math.PI * 2); tint(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y); ctx.moveTo(x, y - 4); ctx.lineTo(x, y + 4); ctx.stroke();
      return [x - r.rx * sx, y - r.ry * sy - 3];
    }
    case "circle": {
      const x = (r.cx + 0.5) * sx, y = (r.cy + 0.5) * sy;
      ctx.beginPath(); ctx.ellipse(x, y, r.r * sx, r.r * sy, 0, 0, Math.PI * 2); tint(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y); ctx.moveTo(x, y - 4); ctx.lineTo(x, y + 4); ctx.stroke();
      return [x - r.r * sx, y - r.r * sy - 3];
    }
    case "polyline": {
      ctx.beginPath();
      r.points.forEach(([x, y], i) => { const px = (x + 0.5) * sx, py = (y + 0.5) * sy; if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py); });
      ctx.stroke();
      for (const [x, y] of r.points) { ctx.beginPath(); ctx.arc((x + 0.5) * sx, (y + 0.5) * sy, 3, 0, Math.PI * 2); ctx.stroke(); }
      return [Math.min(...r.points.map((p) => (p[0] + 0.5) * sx)), Math.min(...r.points.map((p) => (p[1] + 0.5) * sy)) - 3];
    }
    case "line": {
      const ax = (r.x0 + 0.5) * sx, ay = (r.y0 + 0.5) * sy, bx = (r.x1 + 0.5) * sx, by = (r.y1 + 0.5) * sy;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      for (const [px, py] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.stroke(); }
      return [Math.min(ax, bx), Math.min(ay, by) - 3];
    }
    case "polygon": {
      ctx.beginPath();
      r.points.forEach(([px, py], i) => { const x = (px + 0.5) * sx, y = (py + 0.5) * sy; if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
      if (r.points.length >= 3) { ctx.closePath(); tint(); }
      ctx.stroke();
      for (const [px, py] of r.points) { ctx.beginPath(); ctx.arc((px + 0.5) * sx, (py + 0.5) * sy, 3, 0, Math.PI * 2); ctx.stroke(); }
      const [fx, fy] = r.points[0];
      return [(fx + 0.5) * sx, (fy + 0.5) * sy - 6];
    }
  }
}

/** Canvas layer over the image: ROI shapes and value labels in image-pixel coordinates. */
/** Hot (▲, warm colour) / cold (▽, cool colour) pixel markers, Research Studio style. */
function drawMarker(ctx: CanvasRenderingContext2D, x: number, y: number, kind: "hot" | "cold", scrim: string): void {
  const s = 5;
  ctx.save();
  ctx.beginPath();
  if (kind === "hot") { ctx.moveTo(x, y - s); ctx.lineTo(x + s, y + s); ctx.lineTo(x - s, y + s); }
  else { ctx.moveTo(x, y + s); ctx.lineTo(x + s, y - s); ctx.lineTo(x - s, y - s); }
  ctx.closePath();
  ctx.fillStyle = kind === "hot" ? "#ff3b30" : "#4cc9f0";
  ctx.strokeStyle = scrim; ctx.lineWidth = 1.5;
  ctx.fill(); ctx.stroke();
  ctx.restore();
}

export function RoiOverlay(p: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const scope = p.labelScope ?? "live";
  const [offsets, setOffsets] = useState<Offsets>(() => loadOffsets(storage, scope));
  const scopeRef = useRef(scope);
  useEffect(() => { if (scopeRef.current !== scope) { scopeRef.current = scope; setOffsets(loadOffsets(storage, scope)); } }, [scope]);
  // Chip rectangles from the last draw (screen px), for hit-testing a label drag.
  const chipRects = useRef<ChipRect[]>([]);
  const drag = useRef<{ id: number; startX: number; startY: number; dx0: number; dy0: number; moved: boolean } | null>(null);

  const localXY = (e: PE): [number, number] => {
    const r = (e.currentTarget as HTMLCanvasElement).getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const onDown = (e: PE) => {
    if ((p.tool ?? "select") === "select") {
      const [x, y] = localXY(e);
      const id = hitChip(chipRects.current, x, y);
      if (id !== null) {
        const o = offsets[id] ?? { dx: 0, dy: 0 };
        drag.current = { id, startX: x, startY: y, dx0: o.dx, dy0: o.dy, moved: false };
        (e.currentTarget as HTMLCanvasElement).setPointerCapture?.(e.pointerId);
        e.preventDefault();
        return; // do NOT start an ROI draw/selection under the label
      }
    }
    p.onPointerDown(e);
  };
  const onMove = (e: PE) => {
    const d = drag.current;
    if (d) {
      const [x, y] = localXY(e);
      if (Math.abs(x - d.startX) > 2 || Math.abs(y - d.startY) > 2) d.moved = true;
      (e.currentTarget as HTMLCanvasElement).style.cursor = "grabbing";
      setOffsets((cur) => ({ ...cur, [d.id]: { dx: d.dx0 + (x - d.startX), dy: d.dy0 + (y - d.startY) } }));
      return;
    }
    if ((p.tool ?? "select") === "select") {  // show a grab cursor over a draggable label
      const [x, y] = localXY(e);
      (e.currentTarget as HTMLCanvasElement).style.cursor = hitChip(chipRects.current, x, y) !== null ? "grab" : p.cursor;
    }
    p.onPointerMove(e);
  };
  const endDrag = (): boolean => {
    const d = drag.current;
    if (!d) return false;
    drag.current = null;
    setOffsets((cur) => { saveOffsets(storage, scope, cur); return cur; });
    return true;
  };
  const onUp = (e: PE) => { if (endDrag()) return; p.onPointerUp(e); };
  const onDbl = (e: RMouseEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const id = hitChip(chipRects.current, e.clientX - r.left, e.clientY - r.top);
    if (id !== null && offsets[id]) {  // double-click a moved label snaps it back to auto
      setOffsets((cur) => { const next = { ...cur }; delete next[id]; saveOffsets(storage, scope, next); return next; });
      return;
    }
    p.onDoubleClick?.(e);
  };

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.round(p.box.width * dpr));
    const H = Math.max(1, Math.round(p.box.height * dpr));
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, p.box.width, p.box.height);
    if (p.hidden) { chipRects.current = []; return; }  // ROI overlays toggled off (view only)
    BASE.set(ctx, ctx.getTransform());  // CSS-pixel space at device resolution; labels draw in this
    if (p.flipH || p.flipV) { ctx.translate(p.flipH ? p.box.width : 0, p.flipV ? p.box.height : 0); ctx.scale(p.flipH ? -1 : 1, p.flipV ? -1 : 1); }
    const sx = p.box.width / p.width;
    const sy = p.box.height / p.height;
    const scrim = cssVar("--scrim");
    const accent = cssVar("--accent");
    ctx.font = `11px ${cssVar("--font-mono")}`;
    const base = BASE.get(ctx) ?? new DOMMatrix();
    // pass 1: shapes, selection, vertices, hot/cold markers; collect label chips for a later pass
    const labels: { id: number; content: ChipContent; color: string; ax: number; ay: number; selected: boolean }[] = [];
    p.rois.forEach((r, i) => {
      if (r.hidden) return; // keep i so default colours match the rows
      const color = resolve(roiColor(r, i));
      const sel = p.selectedIds ? p.selectedIds.includes(r.id) : r.id === p.selected;
      ctx.strokeStyle = color;
      ctx.lineWidth = sel ? 2.5 : 1;
      ctx.setLineDash([]);
      const [lx, ly] = drawShape(ctx, r, sx, sy, true);
      if (sel) { ctx.strokeStyle = accent; ctx.lineWidth = 1; ctx.setLineDash([3, 3]); drawShape(ctx, r, sx, sy, false); ctx.setLineDash([]); }
      // the label anchor in unflipped screen space, so a mirrored image never mirrors the text
      const scr = base.inverse().transformPoint(ctx.getTransform().transformPoint(new DOMPoint(lx, ly)));
      labels.push({ id: r.id, content: labelContent(r, p.stats.get(r.id)), color, ax: scr.x, ay: scr.y, selected: r.id === p.selected });
      if (r.id === p.selected) for (const [vx, vy] of vertexHandles(r)) {
        const hx = (vx + 0.5) * sx, hy = (vy + 0.5) * sy;
        ctx.setLineDash([]); ctx.fillStyle = accent; ctx.strokeStyle = scrim; ctx.lineWidth = 1.5;
        ctx.fillRect(hx - 3.5, hy - 3.5, 7, 7); ctx.strokeRect(hx - 3.5, hy - 3.5, 7, 7);
      }
      const st = p.stats.get(r.id);
      if (p.extremes !== false && st?.maxAt && st.minAt && st.n > 1) {
        drawMarker(ctx, (st.maxAt[0] + 0.5) * sx, (st.maxAt[1] + 0.5) * sy, "hot", scrim);
        drawMarker(ctx, (st.minAt[0] + 0.5) * sx, (st.minAt[1] + 0.5) * sy, "cold", scrim);
      }
    });
    if (p.draft) {
      ctx.strokeStyle = accent; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      drawShape(ctx, p.draft, sx, sy, false);
    }

    // pass 2: place the label chips without overlap and draw them in screen space
    ctx.save();
    ctx.setTransform(base);
    const meta = new Map(labels.map((l) => [l.id, l]));
    // selected ROI's label keeps its anchor (listed first); the rest flow around it, top-down
    const order = [...labels].sort((a, b) => (b.selected ? 1 : 0) - (a.selected ? 1 : 0) || a.ay - b.ay);
    const items: LabelBox[] = order.map((l) => { const s = chipSize(ctx, l.content); return { id: l.id, ax: l.ax, ay: l.ay - s.h + 3, w: s.w, h: s.h }; });
    const natural = new Map(items.map((it) => [it.id, { x: it.ax, y: it.ay, w: it.w, h: it.h }]));
    const auto = layoutLabels(items, { width: p.box.width, height: p.box.height });
    // A user-dragged label sits at its natural anchor + saved offset (and gets a leader line);
    // the rest keep the automatic collision-avoiding placement.
    const placed = auto.map((pl) => {
      const off = offsets[pl.id];
      if (!off) return pl;
      const nat = natural.get(pl.id)!;
      return { ...pl, x: nat.x + off.dx, y: nat.y + off.dy, displaced: true };
    });
    for (const pl of placed) { // leader lines first, under the chips
      if (!pl.displaced) continue;
      const l = meta.get(pl.id)!;
      ctx.globalAlpha = 0.55; ctx.strokeStyle = l.color; ctx.lineWidth = 1; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(l.ax, l.ay); ctx.lineTo(pl.x + PAD + DOTR, pl.y + LINE1_H / 2); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // draw non-selected first, the selected label last so it is always on top
    for (const pl of [...placed].sort((a, b) => (meta.get(a.id)!.selected ? 1 : 0) - (meta.get(b.id)!.selected ? 1 : 0))) {
      const l = meta.get(pl.id)!;
      drawChip(ctx, pl.x, pl.y, l.content, l.color);
    }
    chipRects.current = placed.map((pl) => { const s = natural.get(pl.id)!; return { id: pl.id, x: pl.x, y: pl.y, w: s.w, h: s.h }; });
    ctx.restore();
  });

  return (
    <canvas ref={ref} className="overlay" tabIndex={0} aria-label="regions of interest"
      style={{ left: p.box.left, top: p.box.top, width: p.box.width, height: p.box.height, cursor: p.cursor }}
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
      onPointerLeave={p.onPointerLeave} onKeyDown={p.onKeyDown} onDoubleClick={onDbl} />
  );
}
