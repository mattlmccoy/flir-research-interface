import { useEffect, useRef } from "react";
import type { KeyboardEvent as RKeyboardEvent, MouseEvent as RMouseEvent, PointerEvent as RPointerEvent } from "react";
import { roiLabel, type Roi, type RoiInput, type RoiStats } from "../lib/roi.ts";
import { roiColor, type Box, vertexHandles } from "../lib/overlay.ts";
import { layoutLabels, type LabelBox } from "../lib/labels.ts";

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
const CHIP_H = 18, PAD = 5, DOTR = 3, SEGGAP = 7;
const NAME_COLOR = "#e8eaed", VALUE_COLOR = "#ffffff", DIM_COLOR = "#9aa0a6";
const CHIP_BG = "rgba(12,14,18,0.9)", CHIP_BORDER = "rgba(255,255,255,0.14)";

interface Seg { text: string; color: string; }

/** The text segments of a label: name (near-white), mean value (bright), and — only for the
 * selected ROI — the min–max range (dim). Keeping unselected chips to name+mean keeps them narrow
 * so they crowd and stack far less; the full range for the one you're inspecting stays visible. */
function labelSegments(r: Roi, s: RoiStats | undefined, full: boolean): Seg[] {
  const segs: Seg[] = [{ text: roiLabel(r), color: NAME_COLOR }];
  if (!s) return segs;
  if (s.n === 0 || s.mean === null) { segs.push({ text: "n/a", color: DIM_COLOR }); return segs; }
  segs.push({ text: `${s.mean.toFixed(1)}°`, color: VALUE_COLOR });
  if (full && r.kind !== "spot" && s.min != null && s.max != null) {
    segs.push({ text: `${Math.round(s.min)}–${Math.round(s.max)}`, color: DIM_COLOR });
  }
  return segs;
}

function chipWidth(ctx: CanvasRenderingContext2D, segs: Seg[]): number {
  let w = PAD + DOTR * 2 + 5; // left pad + dot + gap
  segs.forEach((sg, i) => { w += (i > 0 ? SEGGAP : 0) + ctx.measureText(sg.text).width; });
  return w + PAD;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  if (typeof ctx.roundRect === "function") { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); return; }
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

/** Draws one label chip (dark rounded pill, colour dot, then the segments) at screen (x, y). */
function drawChip(ctx: CanvasRenderingContext2D, x: number, y: number, segs: Seg[], dotColor: string): void {
  const w = chipWidth(ctx, segs);
  roundRect(ctx, x, y, w, CHIP_H, 4);
  ctx.fillStyle = CHIP_BG; ctx.fill();
  ctx.strokeStyle = CHIP_BORDER; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.stroke();
  ctx.beginPath(); ctx.arc(x + PAD + DOTR, y + CHIP_H / 2, DOTR, 0, Math.PI * 2); ctx.fillStyle = dotColor; ctx.fill();
  let cx = x + PAD + DOTR * 2 + 5;
  const ty = y + CHIP_H / 2 + 4;
  segs.forEach((sg, i) => { if (i > 0) cx += SEGGAP; ctx.fillStyle = sg.color; ctx.fillText(sg.text, cx, ty); cx += ctx.measureText(sg.text).width; });
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
    BASE.set(ctx, ctx.getTransform());  // CSS-pixel space at device resolution; labels draw in this
    if (p.flipH || p.flipV) { ctx.translate(p.flipH ? p.box.width : 0, p.flipV ? p.box.height : 0); ctx.scale(p.flipH ? -1 : 1, p.flipV ? -1 : 1); }
    const sx = p.box.width / p.width;
    const sy = p.box.height / p.height;
    const scrim = cssVar("--scrim");
    const accent = cssVar("--accent");
    ctx.font = `11px ${cssVar("--font-mono")}`;
    const base = BASE.get(ctx) ?? new DOMMatrix();
    // pass 1: shapes, selection, vertices, hot/cold markers; collect label chips for a later pass
    const labels: { id: number; segs: Seg[]; color: string; ax: number; ay: number; selected: boolean }[] = [];
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
      labels.push({ id: r.id, segs: labelSegments(r, p.stats.get(r.id), r.id === p.selected), color, ax: scr.x, ay: scr.y, selected: r.id === p.selected });
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
    const items: LabelBox[] = order.map((l) => ({ id: l.id, ax: l.ax, ay: l.ay - CHIP_H + 3, w: chipWidth(ctx, l.segs), h: CHIP_H }));
    const placed = layoutLabels(items, { width: p.box.width, height: p.box.height });
    for (const pl of placed) { // leader lines first, under the chips
      if (!pl.displaced) continue;
      const l = meta.get(pl.id)!;
      ctx.globalAlpha = 0.55; ctx.strokeStyle = l.color; ctx.lineWidth = 1; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(l.ax, l.ay); ctx.lineTo(pl.x + PAD + DOTR, pl.y + CHIP_H / 2); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // draw non-selected first, the selected label last so it is always on top
    for (const pl of [...placed].sort((a, b) => (meta.get(a.id)!.selected ? 1 : 0) - (meta.get(b.id)!.selected ? 1 : 0))) {
      const l = meta.get(pl.id)!;
      drawChip(ctx, pl.x, pl.y, l.segs, l.color);
    }
    ctx.restore();
  });

  return (
    <canvas ref={ref} className="overlay" tabIndex={0} aria-label="regions of interest"
      style={{ left: p.box.left, top: p.box.top, width: p.box.width, height: p.box.height, cursor: p.cursor }}
      onPointerDown={p.onPointerDown} onPointerMove={p.onPointerMove} onPointerUp={p.onPointerUp}
      onPointerLeave={p.onPointerLeave} onKeyDown={p.onKeyDown} onDoubleClick={p.onDoubleClick} />
  );
}
