import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ExperimentInfo, type Timeline } from "../lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "../lib/protocol.ts";
import type { PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import { SPEEDS, clampIndex, nextFrameDelayMs, speedLabel } from "../lib/playback.ts";
import { ThermalView } from "./ThermalView.tsx";
import { DisplayControls } from "./DisplayControls.tsx";

interface Props {
  name: string;
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  onBack: () => void;
}

export function PlaybackPage(p: Props) {
  const [info, setInfo] = useState<ExperimentInfo | null>(null);
  const [tl, setTl] = useState<Timeline | null>(null);
  const [index, setIndex] = useState(0);
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [shown, setShown] = useState<Range>({ min: 0, max: 100 });
  const [err, setErr] = useState<string | null>(null);
  const cache = useRef(new Map<number, FrameMessage>());
  const timer = useRef<number | null>(null);
  const n = info?.n_frames ?? 0;

  useEffect(() => {
    cache.current.clear();
    Promise.all([api.experiment(p.name), api.timeline(p.name)])
      .then(([i, t]) => { setInfo(i); setTl(t); setIndex(0); })
      .catch((e) => setErr(String(e)));
  }, [p.name]);

  const load = useCallback(async (i: number): Promise<FrameMessage> => {
    const hit = cache.current.get(i);
    if (hit) return hit;
    const msg = decodeFrameMessage(await api.frameBuffer(p.name, i));
    if (cache.current.size > 64) cache.current.delete(cache.current.keys().next().value as number);
    cache.current.set(i, msg);
    return msg;
  }, [p.name]);

  // show the current index; prefetch the next one
  useEffect(() => {
    if (!info || n === 0) return;
    let alive = true;
    load(index).then((m) => { if (alive) setFrame(m); }).catch((e) => setErr(String(e)));
    if (index + 1 < n) void load(index + 1).catch(() => undefined);
    return () => { alive = false; };
  }, [index, info, n, load]);

  // play loop paced by recorded timestamps
  useEffect(() => {
    if (!playing || !tl || n === 0) return;
    if (index >= n - 1) { setPlaying(false); return; }
    const delay = nextFrameDelayMs(tl.t_s[index], tl.t_s[index + 1], speed);
    timer.current = window.setTimeout(() => setIndex((i) => clampIndex(i + 1, n)), delay);
    return () => { if (timer.current !== null) window.clearTimeout(timer.current); };
  }, [playing, index, tl, n, speed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === " ") { e.preventDefault(); setPlaying((v) => !v); }
      if (e.key === "ArrowRight") setIndex((i) => clampIndex(i + 1, n));
      if (e.key === "ArrowLeft") setIndex((i) => clampIndex(i - 1, n));
      if (e.key === "Home") setIndex(0);
      if (e.key === "End") setIndex(clampIndex(n - 1, n));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n]);

  const t = tl ? tl.t_s[index] : 0;
  const hdr = frame?.header;
  const exp = (info?.experiment ?? {}) as Record<string, unknown>;
  const cam = (info?.camera ?? {}) as Record<string, unknown>;
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;

  return (
    <main className="main" style={{ gridTemplateRows: "minmax(0, 1fr) auto" }}>
      <div style={{ gridColumn: 1, gridRow: 1, display: "flex", minHeight: 0, minWidth: 0 }}>
        <ThermalView frame={frame} palette={p.palette} scaleMode={p.scaleMode} manual={p.manual} onScale={setShown} />
      </div>
      <aside className="side" style={{ gridColumn: 2, gridRow: "1 / span 2" }}>
        <div className="row"><button className="secondary" onClick={p.onBack}>← Experiments</button></div>
        <h3>Experiment</h3>
        <div className="kv">
          <span>Name</span><span className="v" style={{ fontSize: 11 }}>{p.name}</span>
          <span>Frames</span><span className="v">{n}</span>
          <span>Duration</span><span className="v">{info ? `${info.duration_s.toFixed(2)} s` : "—"}</span>
          <span>Status</span><span className="v">{info ? (info.complete ? "complete" : "INCOMPLETE") : "—"}</span>
          <span>Format</span><span className="v">{info?.ir_format ?? "—"}</span>
          <span>Range</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
          <span>Emissivity</span><span className="v">{fmtAny((cam.object_parameters as Record<string, unknown> | undefined)?.ObjectEmissivity)}</span>
          {Object.entries(exp).filter(([k]) => k !== "name").map(([k, v]) => (
            <><span key={`k${k}`}>{k}</span><span key={`v${k}`} className="v">{String(v)}</span></>
          ))}
        </div>
        <DisplayControls palette={p.palette} setPalette={p.setPalette} scaleMode={p.scaleMode} setScaleMode={p.setScaleMode} manual={p.manual} setManual={p.setManual} shown={shown} />
        <h3>Measurements (this frame)</h3>
        {hdr ? (
          <div className="kv">
            <span>Center</span><span className="v">{fmt(hdr.center_c)}</span>
            <span>Min</span><span className="v">{fmt(hdr.min_c)}</span>
            <span>Max</span><span className="v">{fmt(hdr.max_c)}</span>
            <span>Mean</span><span className="v">{fmt(hdr.mean_c)}</span>
            <span>Frame id</span><span className="v">{hdr.frame_id}</span>
          </div>
        ) : <div className="muted">loading…</div>}
        {err && <div className="errbox">{err}</div>}
      </aside>
      <div className="bottombar" style={{ gridColumn: 1, gridRow: 2, gap: 10 }}>
        <button className="secondary" onClick={() => setIndex(0)} title="Home">⏮</button>
        <button className="secondary" onClick={() => setIndex((i) => clampIndex(i - 1, n))} title="←">◀︎</button>
        <button className="primary" style={{ minWidth: 70 }} onClick={() => setPlaying((v) => !v)}>{playing ? "Pause" : "Play"}</button>
        <button className="secondary" onClick={() => setIndex((i) => clampIndex(i + 1, n))} title="→">▶︎</button>
        <button className="secondary" onClick={() => setIndex(clampIndex(n - 1, n))} title="End">⏭</button>
        <select value={String(speed)} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => <option key={String(s)} value={String(s)}>{speedLabel(s)}</option>)}
        </select>
        <input type="range" min={0} max={Math.max(n - 1, 0)} value={index} style={{ flex: 1 }}
          onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }} />
        <span style={{ fontFamily: "ui-monospace, monospace", minWidth: 150, textAlign: "right" }}>
          {t.toFixed(3)} s · {index + 1}/{n}
        </span>
      </div>
    </main>
  );
}

function fmt(v: number | null | undefined): string { return v == null ? "—" : `${v.toFixed(2)} °C`; }
function fmtAny(v: unknown): string { return v == null ? "—" : typeof v === "number" ? v.toFixed(2) : String(v); }
