import { useEffect, useRef, useState } from "react";
import type { MouseEvent as RMouseEvent } from "react";
import { niceTicks, valueRange, xToPx, yToPx, type TimeWindow, type ValueRange } from "../lib/plot.ts";
import { assignLabelRows, markColor } from "../lib/events.ts";

/** A plotted series. `dash` (canvas line-dash) marks non-temperature series such as RF power. */
export interface Trace { id: number; label: string; color: string; dash?: number[]; t: ArrayLike<number>; v: ArrayLike<number>; }
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
  /** Optional traces on a secondary right-hand axis (e.g. RF power in W) with their own scale. */
  rightTraces?: Trace[];
  rightUnits?: string;
  /** Show the in-plot key of every trace (default on). */
  legend?: boolean;
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

/** One key entry: a short line sample in the trace's color and dash, then its label. */
function KeyItem({ tr, suffix = "" }: { tr: Trace; suffix?: string }) {
  return (
    <span className="row">
      <svg width="18" height="6" aria-hidden="true"><line x1="0" y1="3" x2="18" y2="3" style={{ stroke: tr.color }} strokeWidth="2" strokeDasharray={tr.dash?.map((d) => d / 2).join(" ")} /></svg>
      {tr.label}{suffix}
    </span>
  );
}

/** Temperature-vs-time canvas plot (spec §3 plot dock): traces, event markers, time cursor. */
export function TimePlot({ traces, markers = [], window: win, range, cursorT = null, units = "°C", emptyText, onSeek, rightTraces, rightUnits = "W", legend = true }: Props) {
  const hasRight = !!rightTraces && rightTraces.length > 0;
  const padRight = hasRight ? 46 : PAD.right;
  const showKey = legend && (traces.length + (rightTraces?.length ?? 0)) > 0;
  const padTop = showKey ? 20 : PAD.top;  // the key gets its own strip above the data
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<{ x: number; y: number; items: { label: string; color: string }[] } | null>(null);

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
    const pw = Math.max(1, size.w - PAD.left - padRight);
    const ph = Math.max(1, size.h - padTop - PAD.bottom);
    const yr = range ?? valueRange(traces) ?? { min: 0, max: 1 };
    const yrR = hasRight ? (valueRange(rightTraces) ?? { min: 0, max: 1 }) : null;
    const line = css("var(--line)"), muted = css("var(--muted)");
    ctx.font = `10px ${css("var(--font-mono)")}`;
    ctx.save();
    ctx.translate(PAD.left, padTop);
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
    if (yrR) {  // secondary (right) axis tick labels, e.g. RF power in W
      ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillStyle = css(rightTraces![0].color);
      const rTicks = niceTicks(yrR.min, yrR.max, Math.max(2, Math.floor(ph / 36)));
      for (const v of rTicks) ctx.fillText(v.toFixed(decimalsFor(rTicks)), pw + 6, Math.round(yToPx(v, yrR, ph)) + 0.5);
      ctx.fillStyle = muted;
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
      ctx.strokeStyle = css(tr.color); ctx.lineWidth = 1.5; ctx.setLineDash(tr.dash ?? []); ctx.beginPath();
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
    if (yrR) {  // secondary-axis traces (RF power), scaled to their own range
      for (const tr of rightTraces!) {
        ctx.strokeStyle = css(tr.color); ctx.lineWidth = 1.5; ctx.setLineDash(tr.dash ?? []); ctx.beginPath();
        let pen = false;
        for (let i = 0; i < tr.t.length; i++) {
          const t = tr.t[i], v = tr.v[i];
          if (t < win.t0 - 1 || t > win.t1 + 1) continue;
          if (!Number.isFinite(v)) { pen = false; continue; }
          const x = xToPx(t, win, pw), y = yToPx(v, yrR, ph);
          if (pen) ctx.lineTo(x, y); else { ctx.moveTo(x, y); pen = true; }
        }
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    // event markers: dashed line + label per event, colored by category (matching the legend), with
    // the labels stacked into rows so close events don't overlap.
    ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    const vis = markers.filter((m) => m.t >= win.t0 && m.t <= win.t1);
    const mx = vis.map((m) => Math.round(xToPx(m.t, win, pw)) + 0.5);
    const rows = assignLabelRows(vis.map((m, i) => ({ x: mx[i] + 3, width: ctx.measureText(m.label).width })));
    // Only draw as many stacked label rows as fit legibly; beyond that the labels would pile into an
    // unreadable wall, so those events are line-only and their labels appear on hover instead.
    const maxRows = Math.max(2, Math.min(4, Math.floor(ph / 52)));
    for (let i = 0; i < vis.length; i++) {
      const col = css(markColor(vis[i].label));
      ctx.strokeStyle = col; ctx.fillStyle = col;
      ctx.beginPath(); ctx.moveTo(mx[i], 0); ctx.lineTo(mx[i], ph); ctx.stroke();
      if (rows[i] < maxRows) ctx.fillText(vis[i].label, mx[i] + 3, 2 + rows[i] * 11);
    }
    ctx.setLineDash([]);
    if (cursorT !== null && cursorT >= win.t0 && cursorT <= win.t1) {
      const x = Math.round(xToPx(cursorT, win, pw)) + 0.5;
      ctx.strokeStyle = css("var(--fg-strong)"); ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, ph); ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = muted; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(units, 4, 2);
    if (yrR) {  // right-axis unit (RF power)
      ctx.fillStyle = css(rightTraces![0].color); ctx.textAlign = "right";
      ctx.fillText(rightUnits, size.w - 4, 2);
    }
  }, [traces, markers, win, range, cursorT, units, size, rightTraces, rightUnits, hasRight, padRight, padTop]);

  function onClick(e: RMouseEvent<HTMLCanvasElement>) {
    if (!onSeek) return;
    const r = e.currentTarget.getBoundingClientRect();
    const pw = Math.max(1, r.width - PAD.left - padRight);
    const f = (e.clientX - r.left - PAD.left) / pw;
    if (f < 0 || f > 1) return;
    onSeek(win.t0 + f * (win.t1 - win.t0));
  }

  // Reveal the label(s) of any event marker under the cursor — the fallback for crowded events whose
  // static labels were dropped, and a precise readout for the rest.
  function onMove(e: RMouseEvent<HTMLCanvasElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const pw = Math.max(1, r.width - PAD.left - padRight);
    const cx = e.clientX - r.left;
    const near = markers.filter((m) => m.t >= win.t0 && m.t <= win.t1
      && Math.abs(PAD.left + xToPx(m.t, win, pw) - cx) <= 6);
    setHover(near.length
      ? { x: cx, y: e.clientY - r.top, items: near.map((m) => ({ label: m.label, color: css(markColor(m.label)) })) }
      : null);
  }

  return (
    <div className="plot" ref={hostRef}>
      <canvas ref={canvasRef} style={{ width: size.w, height: size.h, cursor: onSeek ? "crosshair" : "default" }} onClick={onClick} onMouseMove={onMove} onMouseLeave={() => setHover(null)} aria-label="temperature vs time" />
      {hover && (
        <div className="plot-evtip" style={{ left: Math.round(hover.x), top: Math.round(hover.y) }}>
          {hover.items.map((it, i) => (
            <span className="row" key={i}><i className="dot" style={{ background: it.color }} />{it.label}</span>
          ))}
        </div>
      )}
      {showKey && (
        <div className="plot-key" aria-label="plot key" style={{ left: PAD.left, right: padRight + 24 }}>
          {traces.map((tr) => <KeyItem key={`l${tr.id}`} tr={tr} />)}
          {hasRight && rightTraces!.map((tr) => <KeyItem key={`r${tr.id}`} tr={tr} suffix={` (${rightUnits}, right)`} />)}
        </div>
      )}
      {traces.length === 0 && emptyText && <div className="plot-empty">{emptyText}</div>}
    </div>
  );
}
