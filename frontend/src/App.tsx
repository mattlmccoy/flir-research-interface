import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, type RecordingStatus, type Status } from "./lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "./lib/protocol.ts";
import type { PaletteName } from "./lib/palette.ts";
import type { Range, ScaleMode } from "./lib/scale.ts";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout } from "./lib/layout.ts";
import { EMPTY_ROIS, loadRois, roiLabel, roiReducer, saveRois } from "./lib/roi.ts";
import { TraceBuffer, WINDOWS, visibleWindow, windowLabel } from "./lib/plot.ts";
import { traceColor } from "./lib/overlay.ts";
import { fmtAny, fmtCelsius, kelvinToCelsiusLabel } from "./lib/format.ts";
import { ThermalView, type StatsMap } from "./components/ThermalView.tsx";
import { DisplayControls } from "./components/DisplayControls.tsx";
import { SetupPage } from "./components/SetupPage.tsx";
import { RecordPanel } from "./components/RecordPanel.tsx";
import { RoiRows } from "./components/RoiRows.tsx";
import { TimePlot, type Trace } from "./components/TimePlot.tsx";
import { ExperimentsPage } from "./components/ExperimentsPage.tsx";
import { PlaybackPage } from "./components/PlaybackPage.tsx";
import { StudioFrame } from "./components/studio/StudioFrame.tsx";
import { ToolStrip } from "./components/studio/ToolStrip.tsx";
import { Rail } from "./components/studio/Rail.tsx";
import { RailSection } from "./components/studio/RailSection.tsx";
import { PlotDock } from "./components/studio/PlotDock.tsx";
import { StatusBar } from "./components/studio/StatusBar.tsx";

type Page = "live" | "setup" | "experiments" | "playback";
const storage = (() => {
  try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; }
})();
/** ~10 min of live trace at 15 Hz per ROI. */
const MAX_TRACE_POINTS = 9000;

export function App() {
  const [page, setPage] = useState<Page>("setup");
  const [openExp, setOpenExp] = useState<string | null>(null);
  const [layout, dispatch] = useReducer(layoutReducer, DEFAULT_LAYOUT, () => loadLayout(storage));
  useEffect(() => { saveLayout(storage, layout); }, [layout]);
  const [rois, roiDispatch] = useReducer(roiReducer, EMPTY_ROIS, () => loadRois(storage));
  useEffect(() => { saveRois(storage, rois); }, [rois]);

  const [status, setStatus] = useState<Status>({ state: "disconnected" });
  const [recording, setRecording] = useState<RecordingStatus | null>(null);
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [palette, setPalette] = useState<PaletteName>("iron");
  const [scaleMode, setScaleMode] = useState<ScaleMode>("auto");
  const [manual, setManual] = useState<Range>({ min: 20, max: 40 });
  const [shown, setShown] = useState<Range>({ min: 0, max: 100 });
  const [wsFps, setWsFps] = useState(0);
  const [lastFrameAt, setLastFrameAt] = useState(0);
  const fpsCounter = useRef({ n: 0, t: performance.now() });
  const [info, setInfo] = useState<Record<string, unknown> | null>(null);

  // Live traces: one ring buffer per ROI, time relative to the first frame seen this connection.
  const buffers = useRef(new Map<number, TraceBuffer>());
  const t0Ref = useRef<number | null>(null);
  const [liveStats, setLiveStats] = useState<StatsMap>(new Map());
  const [liveWindow, setLiveWindow] = useState(60);
  const onStats = useCallback((m: StatsMap, f: FrameMessage) => {
    if (t0Ref.current === null) t0Ref.current = f.header.device_timestamp_ns;
    const t = (f.header.device_timestamp_ns - t0Ref.current) / 1e9;
    for (const [id, s] of m) {
      let b = buffers.current.get(id);
      if (!b) { b = new TraceBuffer(MAX_TRACE_POINTS); buffers.current.set(id, b); }
      if (b.lastT !== t) b.push(t, s.mean);
    }
    for (const id of Array.from(buffers.current.keys())) if (!m.has(id)) buffers.current.delete(id);
    setLiveStats(m);
  }, []);

  const refresh = useCallback(async () => {
    try { setStatus(await api.status()); } catch { setStatus({ state: "unreachable" }); }
    try { setRecording(await api.recordingStatus()); } catch { /* keep last */ }
  }, []);
  useEffect(() => { void refresh(); const id = setInterval(refresh, 1000); return () => clearInterval(id); }, [refresh]);

  useEffect(() => {
    if (status.state !== "acquiring") return;
    let alive = true;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/frames`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (ev) => {
      if (!alive || typeof ev.data === "string") return;
      try {
        setFrame(decodeFrameMessage(ev.data as ArrayBuffer));
        setLastFrameAt(performance.now());
        const c = fpsCounter.current; c.n += 1;
        const dt = performance.now() - c.t;
        if (dt >= 1000) { setWsFps((c.n * 1000) / dt); c.n = 0; c.t = performance.now(); }
      } catch (e) { console.error(e); }
    };
    api.info().then(setInfo).catch(() => undefined);
    return () => { alive = false; ws.close(); };
  }, [status.state]);

  const stale = status.state === "acquiring" && lastFrameAt > 0 && performance.now() - lastFrameAt > 2000;
  const dot = status.state === "acquiring" && !stale ? "live" : status.state === "error" ? "err"
    : status.state === "disconnected" ? "" : "warn";

  async function disconnect() {
    await api.disconnect();
    setFrame(null);
    buffers.current.clear();
    t0Ref.current = null;
    await refresh();
    setPage("setup");
  }

  const hdr = frame?.header;
  const cam = info ?? {};
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;
  const obj = cam.object_parameters as Record<string, unknown> | undefined;
  const nearLimit = hdr && active && hdr.max_c != null && active.high_c != null && hdr.max_c > active.high_c - 10;
  const allHidden = !layout.strip && !layout.rail && !layout.dock;

  const nowT = hdr && t0Ref.current !== null ? (hdr.device_timestamp_ns - t0Ref.current) / 1e9 : 0;
  const traces: Trace[] = rois.rois.map((r, i) => {
    const b = buffers.current.get(r.id);
    return { id: r.id, label: roiLabel(r), color: traceColor(i), t: b?.t ?? [], v: b?.v ?? [] };
  });

  const topbar = (
    <>
      <span className="wordmark">FLIR RESEARCH INTERFACE</span>
      <nav className="tabs">
        <button className={page === "live" ? "active" : ""} aria-current={page === "live" ? "page" : undefined} onClick={() => setPage("live")}>live</button>
        <button className={page === "experiments" || page === "playback" ? "active" : ""} aria-current={page === "experiments" || page === "playback" ? "page" : undefined} onClick={() => setPage("experiments")}>experiments</button>
        <button className={page === "setup" ? "active" : ""} aria-current={page === "setup" ? "page" : undefined} onClick={() => setPage("setup")}>setup</button>
      </nav>
      <button className="secondary" aria-pressed={allHidden} title={allHidden ? "Restore panels" : "Hide panels (image only)"}
        onClick={() => dispatch({ type: allHidden ? "restoreAll" : "collapseAll" })}>⛶</button>
      <span className="conn">
        <span className={`dot ${dot}`} />
        <span className="who">{status.device ? `${status.device.model} · ${status.device.serial}` : "no camera"}</span>
        <span>· {stale ? "no frames" : status.state}</span>
        {status.state !== "disconnected" && status.state !== "unreachable" && <button className="secondary" onClick={disconnect}>disconnect</button>}
      </span>
    </>
  );

  const statusbar = <StatusBar status={status} recording={recording} displayFps={wsFps} stale={stale} />;

  if (page === "setup") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<SetupPage onConnected={() => { void refresh(); setPage("live"); }} />} />;
  }
  if (page === "experiments") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<ExperimentsPage onOpen={(name) => { setOpenExp(name); setPage("playback"); }} />} />;
  }
  if (page === "playback" && openExp) {
    return <PlaybackPage name={openExp} layout={layout} dispatch={dispatch} topbar={topbar}
      rois={rois} roiDispatch={roiDispatch}
      palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode}
      manual={manual} setManual={setManual} onBack={() => setPage("experiments")} status={status} recording={recording} />;
  }

  return (
    <StudioFrame layout={layout} topbar={topbar} statusbar={statusbar}
      strip={<ToolStrip tool={layout.tool} onTool={(t) => dispatch({ type: "setTool", tool: t })} onCollapseAll={() => dispatch({ type: "collapseAll" })} />}
      center={<ThermalView frame={frame} palette={palette} scaleMode={scaleMode} manual={manual} onScale={setShown}
        rois={rois.rois} selected={rois.selected} tool={layout.tool} onRoi={roiDispatch} onStats={onStats} />}
      dock={
        <PlotDock onCollapse={() => dispatch({ type: "toggle", panel: "dock" })}
          controls={
            <select value={String(liveWindow)} onChange={(e) => setLiveWindow(Number(e.target.value))} aria-label="Plot time window">
              {WINDOWS.map((w) => <option key={String(w)} value={String(w)}>{windowLabel(w)}</option>)}
            </select>
          }>
          <TimePlot traces={traces} window={visibleWindow(nowT, liveWindow, 0)} emptyText="add a spot or rectangle ROI to plot its temperature" />
        </PlotDock>
      }
      rail={
        <Rail>
          <RailSection title="measurements" open={layout.sections.measurements} onToggle={() => dispatch({ type: "toggleSection", section: "measurements" })}>
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmtCelsius(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmtCelsius(hdr.min_c)}</span>
                <span>max</span><span className="v">{fmtCelsius(hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmtCelsius(hdr.mean_c)}</span>
                <span>ir format</span><span className="v plain">{hdr.ir_format}</span>
                <span>frame</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">waiting for frames…</div>}
            {hdr && hdr.kelvin_per_count === null && <div className="errbox">Stream is not temperature-linear; raw counts only.</div>}
            {nearLimit && <div className="warnbox">Max within 10 °C of the range limit ({active?.high_c} °C).</div>}
            <RoiRows rois={rois.rois} stats={liveStats} selected={rois.selected}
              onSelect={(id) => roiDispatch({ type: "select", id })} onRemove={(id) => roiDispatch({ type: "remove", id })} onClear={() => roiDispatch({ type: "clear" })} />
          </RailSection>
          <RailSection title="camera" open={layout.sections.camera} onToggle={() => dispatch({ type: "toggleSection", section: "camera" })} tag="read-only until M6">
            <div className="kv">
              <span>case</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              <span>emissivity</span><span className="v">{fmtAny(obj?.ObjectEmissivity)}</span>
              <span>T reflected</span><span className="v">{kelvinToCelsiusLabel(obj?.ReflectedTemperature)}</span>
              <span>distance</span><span className="v">{obj?.ObjectDistance == null ? "—" : `${fmtAny(obj.ObjectDistance)} m`}</span>
              <span>NUC</span><span className="v plain">{fmtAny(cam.nuc_mode)}</span>
              <span>lens</span><span className="v plain">{fmtAny(cam.lens)}</span>
            </div>
          </RailSection>
          <RailSection title="recording" open={layout.sections.recording} onToggle={() => dispatch({ type: "toggleSection", section: "recording" })}>
            <RecordPanel acquiring={status.state === "acquiring"} />
          </RailSection>
          <RailSection title="display" open={layout.sections.display} onToggle={() => dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode} manual={manual} setManual={setManual} shown={shown} />
          </RailSection>
        </Rail>
      }
    />
  );
}
