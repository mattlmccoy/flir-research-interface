import { NumberField } from "./NumberField.tsx";
import { useState } from "react";
import { api, type Hdf5Export, type ThermalVideoExport } from "../lib/api.ts";
import { roisDifferFromStored, type Roi } from "../lib/roi.ts";

interface Props { name: string; index: number; nFrames: number; rois: Roi[]; celsius: boolean; thermalPreview?: { bytes: number } | null; onThermalPreview?: () => void; files?: { name: string; bytes: number }[]; onRefresh?: () => void; storedRois?: unknown[] | null; }

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
/** Small rotating ring shown inside a button while its export runs. */
const Spinner = () => <span className="spinner" aria-hidden="true" />;

const STEP_LABEL: Record<string, string> = {
  starting: "starting…", "roi series": "writing ROI series…", images: "rendering images…",
  "roi video": "encoding ROI video", done: "done", running: "working…",
};
function progLabel(prog: { step: string; done: number; total: number } | null): string {
  if (!prog) return "regenerating…";
  const base = STEP_LABEL[prog.step] ?? prog.step;
  if (prog.step === "roi video" && prog.total > 0) return `${base} · frame ${prog.done}/${prog.total} (${Math.round((prog.done / prog.total) * 100)}%)`;
  return base;
}
/** Determinate bar when total is known, otherwise an indeterminate sweep. */
function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null;
  return (
    <div className="progressbar" style={{ marginTop: 6 }} role="progressbar" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}>
      <div className={`progressbar-fill${pct === null ? " indeterminate" : ""}`} style={pct === null ? undefined : { width: `${pct}%` }} />
    </div>
  );
}

export function ExportSection({ name, index, nFrames, rois, celsius, thermalPreview, onThermalPreview, files = [], onRefresh, storedRois }: Props) {
  const [busy, setBusy] = useState(false);
  // Which single-flight export (hdf5 / range / report) is running, so only its button spins.
  const [busyKind, setBusyKind] = useState<"hdf5" | "range" | "report" | null>(null);
  const [h5, setH5] = useState<Hdf5Export | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tv, setTv] = useState<ThermalVideoExport | null>(null);
  const [tvBusy, setTvBusy] = useState(false);
  const [rng, setRng] = useState({ start: 0, stop: nFrames, step: 1, format: "csv" });
  const [rngOut, setRngOut] = useState<string | null>(null);
  const [report, setReport] = useState<{ path: string; pages: number; size_bytes: number } | null>(null);
  const [derivedBusy, setDerivedBusy] = useState(false);
  const [derivedOut, setDerivedOut] = useState<string | null>(null);
  const [prog, setProg] = useState<{ step: string; done: number; total: number } | null>(null);
  const storedCount = Array.isArray(storedRois) ? storedRois.length : 0;
  // The derived files (ROI plot, peak frames, ROI video, roi_series.csv) are built from the ROIs
  // stored with the recording. `useOnScreen` persists the current ROIs first; otherwise the
  // recording's own stored ROIs are used. The regenerate runs in the background — poll for progress.
  async function regenerateDerived(useOnScreen: boolean, video = true) {
    setDerivedBusy(true); setErr(null); setDerivedOut(null); setProg({ step: "starting", done: 0, total: 0 });
    try {
      if (useOnScreen) await api.putRois(name, rois);
      await api.exportDerived(name, video);
      for (;;) {
        await new Promise((r) => setTimeout(r, 700));
        const jb = await api.exportDerivedStatus(name);
        setProg({ step: jb.step ?? jb.state, done: jb.done ?? 0, total: jb.total ?? 0 });
        if (jb.state === "done") {
          onThermalPreview?.(); onRefresh?.();
          setDerivedOut(useOnScreen ? `updated to match the ${rois.length} ROI${rois.length === 1 ? "" : "s"} on screen` : `regenerated from the recording's ${storedCount} stored ROI${storedCount === 1 ? "" : "s"}`);
          break;
        }
        if (jb.state === "error") { setErr(jb.error ?? "regenerate failed"); break; }
        if (jb.state === "idle") break;
      }
    } catch (e) { setErr(String(e)); } finally { setDerivedBusy(false); setProg(null); }
  }
  async function makeReport() {
    setBusy(true); setBusyKind("report"); setErr(null);
    try { setReport(await api.exportReport(name)); } catch (e) { setErr(String(e)); } finally { setBusy(false); setBusyKind(null); }
  }
  async function exportRange() {
    setBusy(true); setBusyKind("range"); setErr(null); setRngOut(null);
    try { const r = await api.exportFrames(name, rng.start, Math.min(rng.stop, nFrames), Math.max(1, rng.step), rng.format); setRngOut(`${r.n} frames → ${r.path} (${fmtBytes(r.size_bytes)})`); } catch (e) { setErr(String(e)); } finally { setBusy(false); setBusyKind(null); }
  }
  const haveVideo = !!thermalPreview || !!tv;
  // Do the ROIs on screen still match the ones the derived files (ROI plot, peak frames, ROI
  // video, roi_series.csv) were built from? If not, the derived files are out of date.
  const stale = roisDifferFromStored(rois, storedRois);

  async function renderThermalVideo() {
    setTvBusy(true); setErr(null);
    try { setTv(await api.exportThermalVideo(name)); onThermalPreview?.(); } catch (e) { setErr(String(e)); } finally { setTvBusy(false); }
  }
  async function exportHdf5() {
    setBusy(true); setBusyKind("hdf5"); setErr(null);
    try { setH5(await api.exportHdf5(name)); } catch (e) { setErr(String(e)); } finally { setBusy(false); setBusyKind(null); }
  }
  async function reveal() {
    setErr(null);
    try { const r = await api.reveal(name); if (!r.ok) setErr(r.error ?? "reveal failed"); } catch (e) { setErr(String(e)); }
  }

  const busyElsewhere = busy || tvBusy || nFrames === 0;
  return (
    <>
      {derivedBusy ? (
        <div className="warnbox derived-progress">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}><Spinner /><b>{progLabel(prog)}</b></div>
          <ProgressBar done={prog?.done ?? 0} total={prog?.total ?? 0} />
          <div className="hint" style={{ marginTop: 3 }}>Rendering the ROI-annotated video is the slow step; you can keep working while it finishes.</div>
        </div>
      ) : stale ? (
        <div className="warnbox derived-stale">
          <b>Derived files are out of date.</b> The ROI plot, peak-frame images, thermal-ROI video and roi_series.csv were built from a different set of ROIs than the {rois.length} on screen.
          <div className="row" style={{ marginTop: 8, gap: 6 }}>
            <button className="primary" style={{ flex: "1 1 auto" }} disabled={busyElsewhere} onClick={() => regenerateDerived(true)}
              title="Save the ROIs currently on screen into this run and rebuild every derived file to match.">
              Update with the {rois.length} ROI{rois.length === 1 ? "" : "s"} on screen
            </button>
            <button className="secondary" disabled={busyElsewhere} onClick={() => regenerateDerived(false)}
              title="Leave this run's stored ROIs as they are and rebuild the derived files from them.">
              Keep the {storedCount} stored
            </button>
          </div>
          <button className="linkish" disabled={busyElsewhere} onClick={() => regenerateDerived(true, false)} style={{ marginTop: 6 }}
            title="Update the ROI plot and roi_series.csv (and the peak-frame image) from the ROIs on screen but skip re-rendering the slow ROI video.">
            or just the plot + CSV — skip the video (fast)
          </button>
        </div>
      ) : (files.length > 0 || rois.length > 0) ? (
        <div className="derived-ok">
          <div className="hint" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span aria-hidden="true">✓</span> Derived files match the {rois.length} ROI{rois.length === 1 ? "" : "s"} on screen.
            <button className="secondary" style={{ marginLeft: "auto" }} disabled={busyElsewhere} onClick={() => regenerateDerived(true)} title="Force a re-render of the ROI plot, peak frames, thermal-ROI video and roi_series.csv from the current ROIs">
              re-generate
            </button>
          </div>
          <button className="linkish" disabled={busyElsewhere} onClick={() => regenerateDerived(true, false)} title="Rebuild the ROI plot and roi_series.csv (and the peak-frame image) but skip the slow ROI video.">
            plot + CSV only (skip video)
          </button>
        </div>
      ) : null}
      {!derivedBusy && derivedOut && <div className="hint" style={{ color: "var(--accent)" }}>{derivedOut}</div>}
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
          <button className="secondary" disabled={busy || nFrames === 0} onClick={exportHdf5} title="HDF5: uint16 counts + time axes + metadata, for MATLAB / Python">{busyKind === "hdf5" ? <><Spinner />writing…</> : "HDF5"}</button>
        </span>
        <span>frame range</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 4, justifyContent: "flex-end", alignItems: "center", flexWrap: "wrap" }} title="Export frames start..stop (half-open, 0-based) every step-th frame as a zip of per-frame files, or as one multi-page float TIFF stack">
          <NumberField min={0} max={Math.max(0, nFrames - 1)} value={rng.start} style={{ width: 60 }} aria-label="range start" onChange={(n) => setRng({ ...rng, start: n })} />
          <span className="hint">to</span>
          <NumberField min={1} max={nFrames} value={rng.stop} style={{ width: 60 }} aria-label="range stop" onChange={(n) => setRng({ ...rng, stop: n })} />
          <span className="hint">every</span>
          <NumberField min={1} value={rng.step} style={{ width: 48 }} aria-label="range step" onChange={(n) => setRng({ ...rng, step: n })} />
          <select value={rng.format} aria-label="range format" onChange={(e) => setRng({ ...rng, format: e.target.value })}>
            <option value="csv">CSV zip</option><option value="tiff">TIFF zip</option><option value="tiff-stack">TIFF stack</option><option value="png">PNG zip</option><option value="npy">NPY zip</option>
          </select>
          <button className="secondary" disabled={busy || nFrames === 0} onClick={exportRange}>{busyKind === "range" ? <><Spinner />exporting…</> : "export"}</button>
        </span>
        <span>PDF report</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
          {report && <a className="dl" href={api.reportUrl(name)} target="_blank" rel="noreferrer">open · {report.pages} pages · {fmtBytes(report.size_bytes)}</a>}
          <button className="secondary" disabled={busy || nFrames === 0} onClick={makeReport} title="README text, ROI plot and preview image as one PDF in the run's exports folder">{busyKind === "report" ? <><Spinner />generating…</> : report ? "re-generate" : "generate"}</button>
        </span>
        <span>thermal video</span>
        <span className="v plain" style={{ textAlign: "right", display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
          {haveVideo && <a className="dl" href={api.thermalVideoUrl(name)} download={`${name}_thermal_preview.mp4`} title="exports/thermal_preview.mp4: iron palette, fixed °C scale for the run, colour bar + time label. A viewing copy only; the raw counts stay in thermal.zarr">MP4{fmtBytes(tv?.bytes ?? thermalPreview?.bytes ?? 0) !== "0 kB" ? ` · ${fmtBytes(tv?.bytes ?? thermalPreview?.bytes ?? 0)}` : ""}</a>}
          <button className="secondary" disabled={tvBusy || nFrames === 0} onClick={renderThermalVideo} title="Render (or re-render) the small H.264 viewing copy of the thermal run">{tvBusy ? <><Spinner />rendering…</> : haveVideo ? "re-render" : "render"}</button>
        </span>
      </div>
      {files.length > 0 && (
        <div className="hint" style={{ marginTop: 6 }}>
          <b>Files in this run's exports folder</b> (regenerable; reflect the last regenerate):
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
