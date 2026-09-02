import { useEffect, useRef, useState } from "react";
import { histogram, lineProfile } from "../lib/profile.ts";
import { isArea, roiLabel, type Roi } from "../lib/roi.ts";
import { roiColor } from "../lib/overlay.ts";
import type { Range } from "../lib/scale.ts";

export interface FieldSnapshot { c: Float32Array; w: number; h: number; }

interface Props { field: FieldSnapshot | null; rois: Roi[]; selected: number | null; shown: Range; }

function cssVar(name: string): string { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888"; }

/** Rail section: temperature along the selected line ROI, and a histogram of the frame or the selected area ROI. */
export function ProfilePanel({ field, rois, selected, shown }: Props) {
  const lineRef = useRef<HTMLCanvasElement>(null);
  const histRef = useRef<HTMLCanvasElement>(null);
  const [bins, setBins] = useState(40);
  const sel = rois.find((r) => r.id === selected) ?? null;
  const selIdx = sel ? rois.indexOf(sel) : -1;
  const line = sel && sel.kind === "line" ? sel : null;
  const areaRoi = sel && isArea(sel) && sel.kind !== "line" ? sel : null;

  useEffect(() => {
    const cv = lineRef.current;
    if (!cv || !field || !line) return;
    const p = lineProfile(field.c, field.w, field.h, line);
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const W = cv.width = cv.clientWidth * devicePixelRatio, H = cv.height = 120 * devicePixelRatio;
    ctx.clearRect(0, 0, W, H);
    const vals = p.v.filter((v) => !Number.isNaN(v));
    if (vals.length < 2) return;
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const pad = 6 * devicePixelRatio, dmax = p.d[p.d.length - 1] || 1;
    ctx.strokeStyle = cssVar("--muted"); ctx.lineWidth = 1;
    ctx.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
    ctx.strokeStyle = roiColor(line, selIdx); ctx.lineWidth = 2 * devicePixelRatio;
    ctx.beginPath();
    p.d.forEach((d, i) => {
      const v = p.v[i]; if (Number.isNaN(v)) return;
      const x = pad + (W - 2 * pad) * d / dmax, y = H - pad - (H - 2 * pad) * (v - lo) / span;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = cssVar("--fg"); ctx.font = `${11 * devicePixelRatio}px ${cssVar("--font-mono")}`;
    ctx.fillText(`${hi.toFixed(1)}`, pad + 2, pad + 11 * devicePixelRatio);
    ctx.fillText(`${lo.toFixed(1)}`, pad + 2, H - pad - 3);
    ctx.fillText(`${dmax.toFixed(0)} px`, W - pad - 40 * devicePixelRatio, H - pad - 3);
  }, [field, line, selIdx]);

  useEffect(() => {
    const cv = histRef.current;
    if (!cv || !field) return;
    const h = histogram(field.c, field.w, field.h, areaRoi, { lo: shown.min, hi: shown.max, bins });
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const W = cv.width = cv.clientWidth * devicePixelRatio, H = cv.height = 100 * devicePixelRatio;
    ctx.clearRect(0, 0, W, H);
    const pad = 6 * devicePixelRatio, peak = Math.max(1, ...h.counts);
    const bw = (W - 2 * pad) / h.counts.length;
    ctx.fillStyle = areaRoi ? roiColor(areaRoi, selIdx) : cssVar("--accent");
    h.counts.forEach((c, i) => {
      const bh = (H - 2 * pad) * c / peak;
      ctx.fillRect(pad + i * bw, H - pad - bh, Math.max(1, bw - 1), bh);
    });
    ctx.fillStyle = cssVar("--fg"); ctx.font = `${11 * devicePixelRatio}px ${cssVar("--font-mono")}`;
    ctx.fillText(`${shown.min.toFixed(0)}`, pad, H - 1);
    ctx.fillText(`${shown.max.toFixed(0)} °C`, W - pad - 44 * devicePixelRatio, H - 1);
    ctx.fillText(`${h.n} px${h.below ? ` · ${h.below} below` : ""}${h.above ? ` · ${h.above} above` : ""}`, pad, pad + 11 * devicePixelRatio);
  }, [field, areaRoi, selIdx, shown.min, shown.max, bins]);

  return (
    <>
      <div className="hint">line profile{line ? ` · ${roiLabel(line)}` : ""}</div>
      {line ? <canvas ref={lineRef} style={{ width: "100%", height: 120, display: "block" }} aria-label="temperature along the selected line" />
        : <div className="muted" style={{ fontSize: 12 }}>select a line ROI to see the temperature along it</div>}
      <div className="row" style={{ marginTop: 6 }}>
        <span className="hint">histogram · {areaRoi ? roiLabel(areaRoi) : "whole frame"} · shown range</span>
        <select value={bins} onChange={(e) => setBins(Number(e.target.value))} aria-label="histogram bins" style={{ marginLeft: "auto" }}>
          {[20, 40, 80].map((b) => <option key={b} value={b}>{b} bins</option>)}
        </select>
      </div>
      <canvas ref={histRef} style={{ width: "100%", height: 100, display: "block" }} aria-label="temperature histogram" />
    </>
  );
}
