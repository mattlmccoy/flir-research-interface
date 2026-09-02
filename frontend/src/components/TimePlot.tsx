import { useEffect, useRef, useState } from "react";
import type { MouseEvent as RMouseEvent } from "react";
import { niceTicks, valueRange, xToPx, yToPx, type TimeWindow, type ValueRange } from "../lib/plot.ts";

export interface Trace { id: number; label: string; color: string; t: ArrayLike<number>; v: ArrayLike<number>; }
export interface Marker { t: number; label: string; }

interface Props {
  traces: Trace[];
  markers?: Marker[];
  window: TimeWindow;
  /** Fixed value range; when omitted the plot auto-scales to the visible traces. */
  range?: ValueRange | null;
  cursorT?: number | null;
  units?: string;
  emptyText?: string;
  onSeek?: (t: number) => void;
}

const PAD = { left: 56, right: 10, top: 8, bottom: 20 };

/** Decimal places needed so consecutive tick labels never collide (step 0.5 → 1, step 10 → 0). */
function decimalsFor(ticks: number[]): number {
  if (ticks.length < 2) return 0;
  const step = Math.abs(ticks[1] - ticks[0]);
  return step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step)));
}

function css(color: string): string {
  const m = /^var\((--[a-z0-9-]+)\)$/i.exec(color.trim());
  const root = getComputedStyle(document.documentElement);
  return m ? root.getPropertyValue(m[1]).trim() || "#fff" : color;
}

/** Temperature-vs-time canvas plot (spec §3 plot dock): traces, event markers, time cursor. */
export function TimePlot({ traces, markers = [], window: win, range, cursorT = null, units = "°C", emptyText, onSeek }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setSize({ w: host.clientWidth, h: host.clientHeight }));
    ro.observe(host);
    setSize({ w: host.clientWidth, h: host.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = canvasRef.current;
    if (!c || size.w === 0 || size.h === 0) return;
    const dpr = globalThis.devicePixelRatio || 1;
    c.width = Math.round(size.w * dpr); c.height = Math.round(size.h * dpr);
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    const pw = Math.max(1, size.w - PAD.left - PAD.right);
    const ph = Math.max(1, size.h - PAD.top - PAD.bottom);
    const yr = range ?? valueRange(traces) ?? { min: 0, max: 1 };
    const line = css("var(--line)"), muted = css("var(--muted)");
    ctx.font = `10px ${css("var(--font-mono)")}`;
    ctx.save();
    ctx.translate(PAD.left, PAD.top);
    // grid + axes labels
    ctx.strokeStyle = line; ctx.fillStyle = muted; ctx.lineWidth = 1;
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    const yTicks = niceTicks(yr.min, yr.max, Math.max(2, Math.floor(ph / 36)));
    const yDec = decimalsFor(yTicks);
    for (const v of yTicks) {
      const y = Math.round(yToPx(v, yr, ph)) + 0.5;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(pw, y); ctx.stroke();
      ctx.fillText(v.toFixed(yDec), -6, y);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    const xTicks = niceTicks(win.t0, win.t1, Math.max(2, Math.floor(pw / 160)));
    const xDec = decimalsFor(xTicks);
    for (const t of xTicks) {
      const x = Math.round(xToPx(t, win, pw)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ph); ctx.stroke();
      ctx.fillText(`${t.toFixed(xDec)} s`, x, ph + 4);
    }
    ctx.beginPath(); ctx.rect(0, 0, pw, ph); ctx.clip();
    // traces
    for (const tr of traces) {
      ctx.strokeStyle = css(tr.color); ctx.lineWidth = 1.5; ctx.beginPath();
      let pen = false;
      for (let i = 0; i < tr.t.length; i++) {
        const t = tr.t[i], v = tr.v[i];
        if (t < win.t0 - 1 || t > win.t1 + 1) continue;
        if (!Number.isFinite(v)) { pen = false; continue; }
        const x = xToPx(t, win, pw), y = yToPx(v, yr, ph);
        if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
      }
      ctx.stroke();
    }
    // event markers
    ctx.strokeStyle = css("var(--err)"); ctx.fillStyle = css("var(--err)"); ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    for (const m of markers) {
      if (m.t < win.t0 || m.t > win.t1) continue;
      const x = Math.round(xToPx(m.t, win, pw)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ph); ctx.stroke();
      ctx.fillText(m.label, x + 3, 2);
    }
    ctx.setLineDash([]);
    if (cursorT !== null && cursorT >= win.t0 && cursorT <= win.t1) {
      const x = Math.round(xToPx(cursorT, win, pw)) + 0.5;
      ctx.strokeStyle = css("var(--fg-strong)"); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ph); ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = muted; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(units, 4, 2);
  }, [traces, markers, win, range, cursorT, units, size]);

  function onClick(e: RMouseEvent<HTMLCanvasElement>) {
    if (!onSeek) return;
    const r = e.currentTarget.getBoundingClientRect();
    const pw = Math.max(1, r.width - PAD.left - PAD.right);
    const f = (e.clientX - r.left - PAD.left) / pw;
    if (f < 0 || f > 1) return;
    onSeek(win.t0 + f * (win.t1 - win.t0));
  }

  return (
    <div className="plot" ref={hostRef}>
      <canvas ref={canvasRef} style={{ width: size.w, height: size.h, cursor: onSeek ? "crosshair" : "default" }} onClick={onClick} aria-label="temperature vs time" />
      {traces.length === 0 && emptyText && <div className="plot-empty">{emptyText}</div>}
    </div>
  );
}
