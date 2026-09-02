import { useEffect, useRef } from "react";
import type { KeyboardEvent as RKeyboardEvent, PointerEvent as RPointerEvent } from "react";
import { roiLabel, type Roi, type RoiStats } from "../lib/roi.ts";
import { TRACE_TOKENS, type Box } from "../lib/overlay.ts";

export interface DraftRect { x0: number; y0: number; x1: number; y1: number; }

type PE = RPointerEvent<HTMLCanvasElement>;
interface Props {
  box: Box; width: number; height: number;
  rois: Roi[]; selected: number | null; stats: Map<number, RoiStats>; draft: DraftRect | null;
  cursor: string;
  onPointerDown: (e: PE) => void; onPointerMove: (e: PE) => void; onPointerUp: (e: PE) => void;
  onPointerLeave: () => void; onKeyDown: (e: RKeyboardEvent<HTMLCanvasElement>) => void;
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
      let lx: number, ly: number;
      if (r.kind === "rect") {
        const x = r.x0 * sx, y = r.y0 * sy, w = (r.x1 - r.x0) * sx, h = (r.y1 - r.y0) * sy;
        ctx.strokeRect(x + 0.5, y + 0.5, w, h);
        lx = x; ly = y - 3;
      } else {
        const x = (r.x + 0.5) * sx, y = (r.y + 0.5) * sy;
        ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(x - 11, y); ctx.lineTo(x + 11, y); ctx.moveTo(x, y - 11); ctx.lineTo(x, y + 11); ctx.stroke();
        lx = x + 10; ly = y - 8;
      }
      drawLabel(ctx, `${roiLabel(r)}${statText(r, p.stats.get(r.id))}`, lx, ly, sel ? accent : color, scrim, p.box);
    });
    if (p.draft) {
      ctx.strokeStyle = accent; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
      ctx.strokeRect(p.draft.x0 * sx + 0.5, p.draft.y0 * sy + 0.5, (p.draft.x1 - p.draft.x0) * sx, (p.draft.y1 - p.draft.y0) * sy);
    }
  });

  return (
    <canvas ref={ref} className="overlay" tabIndex={0} aria-label="regions of interest"
      style={{ left: p.box.left, top: p.box.top, width: p.box.width, height: p.box.height, cursor: p.cursor }}
      onPointerDown={p.onPointerDown} onPointerMove={p.onPointerMove} onPointerUp={p.onPointerUp}
      onPointerLeave={p.onPointerLeave} onKeyDown={p.onKeyDown} />
  );
}
