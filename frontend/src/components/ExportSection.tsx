import { useState } from "react";
import { api, type Hdf5Export } from "../lib/api.ts";
import type { Roi } from "../lib/roi.ts";

interface Props { name: string; index: number; nFrames: number; rois: Roi[]; celsius: boolean; }

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
export function ExportSection({ name, index, nFrames, rois, celsius }: Props) {
  const [busy, setBusy] = useState(false);
  const [h5, setH5] = useState<Hdf5Export | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
      </div>
      {!celsius && <div className="warnbox">This recording is not temperature-linear: CSV and TIFF carry raw counts.</div>}
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
