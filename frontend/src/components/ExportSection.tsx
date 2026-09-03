import { useState } from "react";
import { api, type Hdf5Export, type ThermalVideoExport } from "../lib/api.ts";
import type { Roi } from "../lib/roi.ts";

interface Props { name: string; index: number; nFrames: number; rois: Roi[]; celsius: boolean; thermalPreview?: { bytes: number } | null; onThermalPreview?: () => void; files?: { name: string; bytes: number }[]; }

const FRAME_FORMATS = [
  { f: "csv", label: "CSV", title: "°C grid (raw counts if not temperature-linear)" },
  { f: "tiff", label: "TIFF", title: "32-bit float °C (uint16 counts if not temperature-linear)" },
  { f: "png", label: "PNG", title: "16-bit raw counts" },
  { f: "npy", label: "NPY", title: "uint16 raw counts (NumPy)" },
] as const;

function fmtBytes(n: number): string {
  return n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${(n / 1e3).toFixed(0)} kB`;
}

/** Playback rail section: downloads derived from the recording (the store itself is never touched). */
export function ExportSection({ name, index, nFrames, rois, celsius, thermalPreview, onThermalPreview, files = [] }: Props) {
  const [busy, setBusy] = useState(false);
  const [h5, setH5] = useState<Hdf5Export | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tv, setTv] = useState<ThermalVideoExport | null>(null);
  const [tvBusy, setTvBusy] = useState(false);
  const [rng, setRng] = useState({ start: 0, stop: nFrames, step: 1, format: "csv" });
  const [rngOut, setRngOut] = useState<string | null>(null);
  const [report, setReport] = useState<{ path: string; pages: number; size_bytes: number } | null>(null);
  async function makeReport() {
    setBusy(true); setErr(null);
    try { setReport(await api.exportReport(name)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function exportRange() {
    setBusy(true); setErr(null); setRngOut(null);
    try { const r = await api.exportFrames(name, rng.start, Math.min(rng.stop, nFrames), Math.max(1, rng.step), rng.format); setRngOut(`${r.n} frames → ${r.path} (${fmtBytes(r.size_bytes)})`); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const haveVideo = !!thermalPreview || !!tv;

  async function renderThermalVideo() {
    setTvBusy(true); setErr(null);
    try { setTv(await api.exportThermalVideo(name)); onThermalPreview?.(); } catch (e) { setErr(String(e)); } finally { setTvBusy(false); }
  }
  async function exportHdf5() {
    setBusy(true); setErr(null);
    try { setH5(await api.exportHdf5(name)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function reveal() {
    setErr(null);
    try { const r = await api.reveal(name); if (!r.ok) setErr(r.error ?? "reveal failed"); } catch (e) { setErr(String(e)); }
  }

  return (
    <>
      <div className="kv">
        <span>ROI series</span>
        <span className="v plain" style={{ textAlign: "right" }}>
          {rois.length ? <a className="dl" href={api.seriesCsvUrl(name, rois)} download>CSV · {rois.length} ROI{rois.length > 1 ? "s" : ""}</a> : <span className="muted">add an ROI first</span>}
        </span>
        <span>frame {index + 1}/{nFrames}</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end" }}>
          {FRAME_FORMATS.map((x) => <a key={x.f} className="dl" href={api.frameExportUrl(name, index, x.f)} download title={x.title}>{x.label}</a>)}
        </span>
        <span>whole run</span>
        <span className="v plain" style={{ textAlign: "right" }}>
          <button className="secondary" disabled={busy || nFrames === 0} onClick={exportHdf5} title="HDF5: uint16 counts + time axes + metadata, for MATLAB / Python">{busy ? "writing…" : "HDF5"}</button>
        </span>
        <span>frame range</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 4, justifyContent: "flex-end", alignItems: "center", flexWrap: "wrap" }} title="Export frames start..stop (half-open, 0-based) every step-th frame as a zip of per-frame files, or as one multi-page float TIFF stack">
          <input type="number" min={0} max={Math.max(0, nFrames - 1)} value={rng.start} style={{ width: 60 }} aria-label="range start" onChange={(e) => setRng({ ...rng, start: Number(e.target.value) })} />
          <span className="hint">to</span>
          <input type="number" min={1} max={nFrames} value={rng.stop} style={{ width: 60 }} aria-label="range stop" onChange={(e) => setRng({ ...rng, stop: Number(e.target.value) })} />
          <span className="hint">every</span>
          <input type="number" min={1} value={rng.step} style={{ width: 48 }} aria-label="range step" onChange={(e) => setRng({ ...rng, step: Number(e.target.value) })} />
          <select value={rng.format} aria-label="range format" onChange={(e) => setRng({ ...rng, format: e.target.value })}>
            <option value="csv">CSV zip</option><option value="tiff">TIFF zip</option><option value="tiff-stack">TIFF stack</option><option value="png">PNG zip</option><option value="npy">NPY zip</option>
          </select>
          <button className="secondary" disabled={busy || nFrames === 0} onClick={exportRange}>export</button>
        </span>
        <span>PDF report</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
          {report && <a className="dl" href={api.reportUrl(name)} target="_blank" rel="noreferrer">open · {report.pages} pages · {fmtBytes(report.size_bytes)}</a>}
          <button className="secondary" disabled={busy || nFrames === 0} onClick={makeReport} title="README text, ROI plot and preview image as one PDF in the run's exports folder">{report ? "re-generate" : "generate"}</button>
        </span>
        <span>thermal video</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
          {haveVideo && <a className="dl" href={api.thermalVideoUrl(name)} download={`${name}_thermal_preview.mp4`} title="exports/thermal_preview.mp4: iron palette, fixed °C scale for the run, colour bar + time label. A viewing copy only; the raw counts stay in thermal.zarr">MP4{fmtBytes(tv?.bytes ?? thermalPreview?.bytes ?? 0) !== "0 kB" ? ` · ${fmtBytes(tv?.bytes ?? thermalPreview?.bytes ?? 0)}` : ""}</a>}
          <button className="secondary" disabled={tvBusy || nFrames === 0} onClick={renderThermalVideo} title="Render (or re-render) the small H.264 viewing copy of the thermal run">{tvBusy ? "rendering…" : haveVideo ? "re-render" : "render"}</button>
        </span>
      </div>
      {files.length > 0 && (
        <div className="hint" style={{ marginTop: 6 }}>
          <b>Files in this run's exports folder</b> (written at stop, regenerable):
          <div className="row" style={{ marginTop: 4 }}>
            {files.map((f) => <a key={f.name} className="dl" href={api.exportFileUrl(name, f.name)} target="_blank" rel="noreferrer" title={fmtBytes(f.bytes)}>{f.name}</a>)}
          </div>
        </div>
      )}
      {!celsius && <div className="warnbox">This recording is not temperature-linear: CSV and TIFF carry raw counts.</div>}
      {rngOut && <div className="hint" style={{ wordBreak: "break-all" }}>{rngOut}</div>}
      {h5 && (
        <div className="hint" style={{ wordBreak: "break-all" }}>
          wrote {fmtBytes(h5.size_bytes)} · {h5.n_frames} frames<br />{h5.path}<br />
          <button className="secondary" style={{ marginTop: 4 }} onClick={reveal}>reveal</button>
        </div>
      )}
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
