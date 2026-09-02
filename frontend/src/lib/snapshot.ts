/**
 * "Save image": the thermal view with its ROI overlay composed into one PNG at native pixel
 * resolution, plus a footer line. Pure helpers here; the canvas work is in saveSnapshot().
 */
import type { Range } from "./scale.ts";

export function snapshotFilename(name: string, index: number | null, tS: number | null): string {
  const safe = name.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "frame";
  const parts = [safe];
  if (index !== null) parts.push(`f${String(index + 1).padStart(4, "0")}`);
  if (tS !== null) parts.push(`t${tS.toFixed(3)}s`);
  return `${parts.join("_")}.png`;
}

export interface FooterInfo { name: string; tS: number | null; index: number | null; range: Range; palette: string; rois: number; reference: boolean; }

export function snapshotFooter(i: FooterInfo): string {
  const parts = [i.name];
  if (i.reference) {
    parts.push(`frame − reference ±${Math.max(Math.abs(i.range.min), Math.abs(i.range.max)).toFixed(1)} °C`);
    return parts.join(" · ");
  }
  if (i.index !== null) parts.push(`frame ${i.index + 1}`);
  if (i.tS !== null) parts.push(`${i.tS.toFixed(3)} s`);
  parts.push(`${i.palette} ${i.range.min.toFixed(1)}–${i.range.max.toFixed(1)} °C`);
  if (i.rois > 0) parts.push(`${i.rois} ROI${i.rois === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

/** Compose every canvas inside `view` (thermal image, ROI overlay) at native size and trigger a download. */
export function saveSnapshot(view: HTMLElement, filename: string, footer: string): boolean {
  const canvases = Array.from(view.querySelectorAll("canvas")) as HTMLCanvasElement[];
  const base = canvases[0];
  if (!base || base.width === 0) return false;
  const pad = 6, fh = 16;
  const out = document.createElement("canvas");
  out.width = base.width;
  out.height = base.height + fh + pad * 2;
  const ctx = out.getContext("2d");
  if (!ctx) return false;
  ctx.fillStyle = "#0b0e12";
  ctx.fillRect(0, 0, out.width, out.height);
  for (const c of canvases) ctx.drawImage(c, 0, 0, base.width, base.height);
  ctx.fillStyle = "#e6e6e6";
  ctx.font = "12px ui-monospace, Menlo, monospace";
  ctx.textBaseline = "middle";
  ctx.fillText(footer, pad, base.height + pad + fh / 2, out.width - 2 * pad);
  const a = document.createElement("a");
  a.href = out.toDataURL("image/png");
  a.download = filename;
  a.click();
  return true;
}
