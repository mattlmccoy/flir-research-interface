import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, type RecordingStatus, type Status } from "./lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "./lib/protocol.ts";
import type { PaletteName } from "./lib/palette.ts";
import type { Range, ScaleMode } from "./lib/scale.ts";
import { DEFAULT_LAYOUT, layoutReducer, loadLayout, saveLayout } from "./lib/layout.ts";
import { ThermalView } from "./components/ThermalView.tsx";
import { DisplayControls } from "./components/DisplayControls.tsx";
import { SetupPage } from "./components/SetupPage.tsx";
import { RecordPanel } from "./components/RecordPanel.tsx";
import { ExperimentsPage } from "./components/ExperimentsPage.tsx";
import { PlaybackPage } from "./components/PlaybackPage.tsx";
import { StudioFrame } from "./components/studio/StudioFrame.tsx";
import { ToolStrip } from "./components/studio/ToolStrip.tsx";
import { Rail } from "./components/studio/Rail.tsx";
import { RailSection } from "./components/studio/RailSection.tsx";
import { PlotDock } from "./components/studio/PlotDock.tsx";
import { StatusBar } from "./components/studio/StatusBar.tsx";

type Page = "live" | "setup" | "experiments" | "playback";
const storage = typeof localStorage !== "undefined" ? localStorage : null;

export function App() {
  const [page, setPage] = useState<Page>("setup");
  const [openExp, setOpenExp] = useState<string | null>(null);
  const [layout, dispatch] = useReducer(layoutReducer, DEFAULT_LAYOUT, () => loadLayout(storage));
  useEffect(() => saveLayout(storage, layout), [layout]);

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
  const info = useRef<Record<string, unknown> | null>(null);

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
    api.info().then((i) => { info.current = i; }).catch(() => undefined);
    return () => { alive = false; ws.close(); };
  }, [status.state]);

  const stale = status.state === "acquiring" && lastFrameAt > 0 && performance.now() - lastFrameAt > 2000;
  const dot = status.state === "acquiring" && !stale ? "live" : status.state === "error" ? "err"
    : status.state === "disconnected" ? "" : "warn";

  async function disconnect() { await api.disconnect(); setFrame(null); await refresh(); setPage("setup"); }

  const hdr = frame?.header;
  const cam = info.current ?? {};
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;
  const obj = cam.object_parameters as Record<string, unknown> | undefined;
  const nearLimit = hdr && active && hdr.max_c != null && active.high_c != null && hdr.max_c > active.high_c - 10;
  const panelsHidden = !layout.strip || !layout.rail || !layout.dock;

  const topbar = (
    <>
      <span className="wordmark">FLIR RESEARCH INTERFACE</span>
      <nav className="tabs">
        <button className={page === "live" ? "active" : ""} onClick={() => setPage("live")}>live</button>
        <button className={page === "experiments" || page === "playback" ? "active" : ""} onClick={() => setPage("experiments")}>experiments</button>
        <button className={page === "setup" ? "active" : ""} onClick={() => setPage("setup")}>setup</button>
      </nav>
      <button className="secondary" aria-label="Toggle panels" title={panelsHidden ? "Restore panels" : "Hide panels (image only)"}
        onClick={() => dispatch({ type: panelsHidden ? "restoreAll" : "collapseAll" })}>⛶</button>
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
      palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode}
      manual={manual} setManual={setManual} onBack={() => setPage("experiments")} status={status} recording={recording} />;
  }

  return (
    <StudioFrame layout={layout} topbar={topbar} statusbar={statusbar}
      strip={<ToolStrip tool={layout.tool} onTool={(t) => dispatch({ type: "setTool", tool: t })} onCollapseAll={() => dispatch({ type: "collapseAll" })} />}
      center={<ThermalView frame={frame} palette={palette} scaleMode={scaleMode} manual={manual} onScale={setShown} />}
      dock={<PlotDock onCollapse={() => dispatch({ type: "toggle", panel: "dock" })} />}
      rail={
        <Rail>
          <RailSection title="measurements" open={layout.sections.measurements} onToggle={() => dispatch({ type: "toggleSection", section: "measurements" })}>
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmt(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmt(hdr.min_c)}</span>
                <span>max</span><span className="v">{fmt(hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmt(hdr.mean_c)}</span>
                <span>ir format</span><span className="v plain">{hdr.ir_format}</span>
                <span>frame</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">waiting for frames…</div>}
            {hdr && hdr.kelvin_per_count === null && <div className="errbox">Stream is not temperature-linear; raw counts only.</div>}
            {nearLimit && <div className="warnbox">Max within 10 °C of the range limit ({active?.high_c} °C).</div>}
          </RailSection>
          <RailSection title="camera" open={layout.sections.camera} onToggle={() => dispatch({ type: "toggleSection", section: "camera" })} tag="read-only until M6">
            <div className="kv">
              <span>case</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              <span>emissivity</span><span className="v">{fmtAny(obj?.ObjectEmissivity)}</span>
              <span>T reflected</span><span className="v">{kelvin(obj?.ReflectedTemperature)}</span>
              <span>distance</span><span className="v">{fmtAny(obj?.ObjectDistance)} m</span>
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

function fmt(v: number | null | undefined): string { return v == null ? "—" : `${v.toFixed(2)} °C`; }
function fmtAny(v: unknown): string { return v == null ? "—" : typeof v === "number" ? v.toFixed(2) : String(v); }
function kelvin(v: unknown): string { return typeof v === "number" ? `${(v - 273.15).toFixed(1)} °C` : "—"; }
