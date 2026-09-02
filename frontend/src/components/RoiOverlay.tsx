import { useEffect, useRef } from "react";
import type { KeyboardEvent as RKeyboardEvent, MouseEvent as RMouseEvent, PointerEvent as RPointerEvent } from "react";
import { roiLabel, type Roi, type RoiInput, type RoiStats } from "../lib/roi.ts";
import { TRACE_TOKENS, type Box } from "../lib/overlay.ts";

/** In-progress shape while the pointer is down / vertices are being placed. */
export type Draft = RoiInput;

type PE = RPointerEvent<HTMLCanvasElement>;
interface Props {
  box: Box; width: number; height: number;
  rois: Roi[]; selected: number | null; stats: Map<number, RoiStats>; draft: Draft | null;
  cursor: string;
  onPointerDown: (e: PE) => void; onPointerMove: (e: PE) => void; onPointerUp: (e: PE) => void;
  onPointerLeave: () => void; onKeyDown: (e: RKeyboardEvent<HTMLCanvasElement>) => void;
  onDoubleClick?: (e: RMouseEvent<HTMLCanvasElement>) => void;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#ffffff";
}

function drawLabel(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, scrim: string, box: Box) {
  const w = ctx.measureText(text).width + 8;
  const lx = Math.min(Math.max(0, x), box.width - w);
  const ly = Math.min(Math.max(14, y), box.height - 2);
  ctx.fillStyle = scrim;
  ctx.fillRect(lx, ly - 13, w, 15);
  ctx.fillStyle = color;
  ctx.fillText(text, lx + 4, ly - 2);
}

function statText(r: Roi, s: RoiStats | undefined): string {
  if (!s) return "";
  if (s.n === 0 || s.mean === null) return " n/a";
  if (r.kind === "spot") return ` ${s.mean.toFixed(2)}`;
  return ` ${s.mean.toFixed(2)}  ${(s.min as number).toFixed(1)}…${(s.max as number).toFixed(1)}`;
}

/** Strokes one shape in canvas pixels; returns where its label goes. */
function drawShape(ctx: CanvasRenderingContext2D, r: RoiInput, sx: number, sy: number): [number, number] {
  switch (r.kind) {
    case "rect": {
      const x = r.x0 * sx, y = r.y0 * sy;
      ctx.strokeRect(x + 0.5, y + 0.5, (r.x1 - r.x0) * sx, (r.y1 - r.y0) * sy);
      return [x, y - 3];
    }
    case "spot": {
      const x = (r.x + 0.5) * sx, y = (r.y + 0.5) * sy;
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 11, y); ctx.lineTo(x + 11, y); ctx.moveTo(x, y - 11); ctx.lineTo(x, y + 11); ctx.stroke();
      return [x + 10, y - 8];
    }
    case "circle": {
      const x = (r.cx + 0.5) * sx, y = (r.cy + 0.5) * sy;
      ctx.beginPath(); ctx.ellipse(x, y, r.r * sx, r.r * sy, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y); ctx.moveTo(x, y - 4); ctx.lineTo(x, y + 4); ctx.stroke();
      return [x - r.r * sx, y - r.r * sy - 3];
    }
    case "line": {
      const ax = (r.x0 + 0.5) * sx, ay = (r.y0 + 0.5) * sy, bx = (r.x1 + 0.5) * sx, by = (r.y1 + 0.5) * sy;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      for (const [px, py] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.stroke(); }
      return [Math.min(ax, bx), Math.min(ay, by) - 3];
    }
    case "polyline": {
      ctx.beginPath();
      r.points.forEach(([px, py], i) => { const x = (px + 0.5) * sx, y = (py + 0.5) * sy; if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
      ctx.stroke();
      for (const [px, py] of r.points) { ctx.beginPath(); ctx.arc((px + 0.5) * sx, (py + 0.5) * sy, 3, 0, Math.PI * 2); ctx.stroke(); }
      const [fx, fy] = r.points[0];
      return [(fx + 0.5) * sx, (fy + 0.5) * sy - 6];
    }
  }
}

/** Canvas layer over the image: ROI shapes and value labels in image-pixel coordinates. */
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
    const sx = p.box.width / p.width;
    const sy = p.box.height / p.height;
    const scrim = cssVar("--scrim");
    const accent = cssVar("--accent");
    ctx.font = `11px ${cssVar("--font-mono")}`;
    p.rois.forEach((r, i) => {
      const color = cssVar(TRACE_TOKENS[i % TRACE_TOKENS.length]);
      const sel = r.id === p.selected;
      ctx.strokeStyle = sel ? accent : color;
      ctx.lineWidth = sel ? 2 : 1;
      ctx.setLineDash([]);
      const [lx, ly] = drawShape(ctx, r, sx, sy);
      drawLabel(ctx, `${roiLabel(r)}${statText(r, p.stats.get(r.id))}`, lx, ly, sel ? accent : color, scrim, p.box);
    });
    if (p.draft) {
      ctx.strokeStyle = accent; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      drawShape(ctx, p.draft, sx, sy);
    }
  });

  return (
    <canvas ref={ref} className="overlay" tabIndex={0} aria-label="regions of interest"
      style={{ left: p.box.left, top: p.box.top, width: p.box.width, height: p.box.height, cursor: p.cursor }}
      onPointerDown={p.onPointerDown} onPointerMove={p.onPointerMove} onPointerUp={p.onPointerUp}
      onPointerLeave={p.onPointerLeave} onKeyDown={p.onKeyDown} onDoubleClick={p.onDoubleClick} />
  );
}
