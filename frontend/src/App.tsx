import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Status } from "./lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "./lib/protocol.ts";
import type { PaletteName } from "./lib/palette.ts";
import type { Range, ScaleMode } from "./lib/scale.ts";
import { ThermalView } from "./components/ThermalView.tsx";
import { SetupPage } from "./components/SetupPage.tsx";
import { RecordPanel } from "./components/RecordPanel.tsx";
import { ExperimentsPage } from "./components/ExperimentsPage.tsx";
import { PlaybackPage } from "./components/PlaybackPage.tsx";
import { DisplayControls } from "./components/DisplayControls.tsx";

type Page = "live" | "setup" | "experiments" | "playback";

export function App() {
  const [page, setPage] = useState<Page>("setup");
  const [openExp, setOpenExp] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ state: "disconnected" });
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [palette, setPalette] = useState<PaletteName>("iron");
  const [scaleMode, setScaleMode] = useState<ScaleMode>("auto");
  const [manual, setManual] = useState<Range>({ min: 20, max: 40 });
  const [shown, setShown] = useState<Range>({ min: 0, max: 100 });
  const [wsFps, setWsFps] = useState(0);
  const [lastFrameAt, setLastFrameAt] = useState<number>(0);
  const fpsCounter = useRef({ n: 0, t: performance.now() });
  const info = useRef<Record<string, unknown> | null>(null);

  const refreshStatus = useCallback(async () => {
    try { setStatus(await api.status()); } catch { setStatus({ state: "unreachable" }); }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const id = setInterval(refreshStatus, 1000);
    return () => clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    if (status.state !== "acquiring") return;
    let alive = true;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/frames`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (ev) => {
      if (!alive) return;
      if (typeof ev.data === "string") return;
      try {
        setFrame(decodeFrameMessage(ev.data as ArrayBuffer));
        setLastFrameAt(performance.now());
        const c = fpsCounter.current;
        c.n += 1;
        const dt = performance.now() - c.t;
        if (dt >= 1000) { setWsFps((c.n * 1000) / dt); c.n = 0; c.t = performance.now(); }
      } catch (e) { console.error(e); }
    };
    api.info().then((i) => { info.current = i; }).catch(() => undefined);
    return () => { alive = false; ws.close(); };
  }, [status.state]);

  const stale = status.state === "acquiring" && lastFrameAt > 0 && performance.now() - lastFrameAt > 2000;
  const dotClass = status.state === "acquiring" && !stale ? "ok" : status.state === "connected" || status.state === "unreachable" ? "warn" : status.state === "error" ? "err" : "";

  async function disconnect() {
    await api.disconnect();
    setFrame(null);
    await refreshStatus();
    setPage("setup");
  }

  const hdr = frame?.header;
  const active = (info.current?.active_case as { low_c?: number; high_c?: number } | undefined) ?? undefined;
  const nearLimit = hdr && active && hdr.max_c != null && active.high_c != null && hdr.max_c > active.high_c - 10;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">FLIR RESEARCH INTERFACE</span>
        <nav className="tabs">
          <button className={page === "live" ? "active" : ""} onClick={() => setPage("live")}>Live</button>
          <button className={page === "setup" ? "active" : ""} onClick={() => setPage("setup")}>Setup</button>
          <button className={page === "experiments" || page === "playback" ? "active" : ""} onClick={() => setPage("experiments")}>Experiments</button>
        </nav>
        <span style={{ marginLeft: "auto" }}>
          <span className={`dot ${dotClass}`} />
          {status.device ? `${status.device.model} · ${status.device.serial}` : "no camera"} · {stale ? "NO FRAMES" : status.state}
        </span>
        {status.state !== "disconnected" && status.state !== "unreachable" && (
          <button className="secondary" onClick={disconnect}>Disconnect</button>
        )}
      </header>

      {page === "setup" ? (
        <SetupPage onConnected={() => { void refreshStatus(); setPage("live"); }} />
      ) : page === "experiments" ? (
        <ExperimentsPage onOpen={(name) => { setOpenExp(name); setPage("playback"); }} />
      ) : page === "playback" && openExp ? (
        <PlaybackPage name={openExp} palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode} manual={manual} setManual={setManual} onBack={() => setPage("experiments")} />
      ) : (
        <main className="main">
          <ThermalView frame={frame} palette={palette} scaleMode={scaleMode} manual={manual} onScale={setShown} />
          <aside className="side">
            <DisplayControls palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode} manual={manual} setManual={setManual} shown={shown} />

            <h3>Measurements</h3>
            {hdr ? (
              <div className="kv">
                <span>Center</span><span className="v">{fmt(hdr.center_c)}</span>
                <span>Min</span><span className="v">{fmt(hdr.min_c)}</span>
                <span>Max</span><span className="v">{fmt(hdr.max_c)}</span>
                <span>Mean</span><span className="v">{fmt(hdr.mean_c)}</span>
                <span>IR format</span><span className="v">{hdr.ir_format}</span>
                <span>Frame</span><span className="v">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">waiting for frames…</div>}
            {hdr && hdr.kelvin_per_count === null && <div className="errbox">Stream is not temperature-linear; values are raw counts, no temperatures shown.</div>}
            {nearLimit && <div className="warnbox">Max temperature within 10 °C of the selected range limit ({active?.high_c} °C).</div>}

            <RecordPanel acquiring={status.state === "acquiring"} />

            <h3>Camera</h3>
            <div className="kv">
              <span>Range</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              <span>Emissivity</span><span className="v">{fmtAny((info.current?.object_parameters as Record<string, unknown> | undefined)?.ObjectEmissivity)}</span>
              <span>Lens</span><span className="v">{fmtAny(info.current?.lens)}</span>
            </div>
          </aside>
        </main>
      )}

      <footer className="bottombar">
        <span>camera {status.camera_fps ? status.camera_fps.toFixed(1) : "—"} fps</span>
        <span>display {wsFps.toFixed(1)} fps</span>
        <span>received {status.frames_received ?? 0}</span>
        <span>viz-dropped {status.viz_dropped ?? 0} <span className="muted">(display only; recording not active)</span></span>
        {status.last_error && <span className="errbox">{status.last_error}</span>}
      </footer>
    </div>
  );
}

function fmt(v: number | null | undefined): string { return v == null ? "—" : `${v.toFixed(2)} °C`; }
function fmtAny(v: unknown): string { return v == null ? "—" : typeof v === "number" ? v.toFixed(2) : String(v); }
