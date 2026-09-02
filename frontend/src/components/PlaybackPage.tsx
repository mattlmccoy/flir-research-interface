import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, ReactNode } from "react";
import { api, type ExperimentInfo, type RecordingStatus, type RoiSeries, type Status, type Timeline } from "../lib/api.ts";
import { decodeFrameMessage, type FrameMessage } from "../lib/protocol.ts";
import type { PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import type { LayoutAction, LayoutState } from "../lib/layout.ts";
import { SPEEDS, clampIndex, nextFrameDelayMs, speedLabel } from "../lib/playback.ts";
import { loadRois, roiLabel, type Roi, type RoiAction, type RoiState } from "../lib/roi.ts";
import { roiColor } from "../lib/overlay.ts";
import { eventsToMarkers, nearestIndex } from "../lib/events.ts";
import { fmtAny, fmtCelsius } from "../lib/format.ts";
import { ThermalView, type StatsMap } from "./ThermalView.tsx";
import { DisplayControls } from "./DisplayControls.tsx";
import { RoiRows } from "./RoiRows.tsx";
import { ExportSection } from "./ExportSection.tsx";
import { MetadataEditor } from "./MetadataEditor.tsx";
import { VisiblePanel, VisibleVideo } from "./VisiblePanel.tsx";
import { loadAlignment, parseAlignment } from "../lib/alignment.ts";
import { TimePlot, type Trace } from "./TimePlot.tsx";
import { StudioFrame } from "./studio/StudioFrame.tsx";
import { ToolStrip } from "./studio/ToolStrip.tsx";
import { Rail } from "./studio/Rail.tsx";
import { RailSection } from "./studio/RailSection.tsx";
import { PlotDock } from "./studio/PlotDock.tsx";
import { StatusBar } from "./studio/StatusBar.tsx";

interface Props {
  name: string;
  layout: LayoutState; dispatch: Dispatch<LayoutAction>; topbar: ReactNode;
  rois: RoiState; roiDispatch: Dispatch<RoiAction>;
  status: Status; recording: RecordingStatus | null;
  palette: PaletteName; setPalette: (p: PaletteName) => void;
  scaleMode: ScaleMode; setScaleMode: (m: ScaleMode) => void;
  manual: Range; setManual: (r: Range) => void;
  onBack: () => void;
}

function seriesTraces(series: RoiSeries | null, rois: RoiState): Trace[] {
  if (!series) return [];
  return rois.rois.flatMap((r, i) => {
    const s = series.series[String(r.id)];
    const raw = s?.value ?? s?.mean;
    if (!raw) return [];
    return [{ id: r.id, label: roiLabel(r), color: roiColor(r, i), t: series.t_s, v: raw.map((v) => (v === null ? NaN : v)) }];
  });
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
  const [stats, setStats] = useState<StatsMap>(new Map());
  const [series, setSeries] = useState<RoiSeries | null>(null);
  const cache = useRef(new Map<number, FrameMessage>());
  const n = info?.n_frames ?? 0;
  const onStats = useCallback((m: StatsMap) => setStats(m), []);

  useEffect(() => {
    cache.current.clear();
    Promise.all([api.experiment(p.name), api.timeline(p.name)])
      .then(([i, t]) => { setInfo(i); setTl(t); setIndex(0); }).catch((e) => setErr(String(e)));
  }, [p.name]);

  // Whole-recording ROI series from the backend; debounced so a drag does not fire per pixel.
  useEffect(() => {
    if (!info || p.rois.rois.length === 0) { setSeries(null); return; }
    let alive = true;
    const id = window.setTimeout(() => {
      api.series(p.name, p.rois.rois).then((s) => { if (alive) setSeries(s); }).catch((e) => { if (alive) setErr(String(e)); });
    }, 250);
    return () => { alive = false; window.clearTimeout(id); };
  }, [p.name, info, p.rois.rois]);

  const load = useCallback(async (i: number): Promise<FrameMessage> => {
    const hit = cache.current.get(i);
    if (hit) return hit;
    const msg = decodeFrameMessage(await api.frameBuffer(p.name, i));
    if (cache.current.size >= 64) cache.current.delete(cache.current.keys().next().value as number);
    cache.current.set(i, msg);
    return msg;
  }, [p.name]);

  useEffect(() => {
    if (!info || n === 0) return;
    let alive = true;
    load(index).then((m) => { if (alive) setFrame(m); }).catch((e) => setErr(String(e)));
    if (index + 1 < n) void load(index + 1).catch(() => undefined);
    return () => { alive = false; };
  }, [index, info, n, load]);

  useEffect(() => {
    if (!playing || !tl || n === 0) return;
    if (index >= n - 1) { setPlaying(false); return; }
    if (!Number.isFinite(speed)) {
      let cancelled = false;
      load(index + 1).then(() => { if (!cancelled) setIndex((i) => clampIndex(i + 1, n)); }).catch(() => setPlaying(false));
      return () => { cancelled = true; };
    }
    const t = window.setTimeout(() => setIndex((i) => clampIndex(i + 1, n)), nextFrameDelayMs(tl.t_s[index], tl.t_s[index + 1], speed));
    return () => window.clearTimeout(t);
  }, [playing, index, tl, n, speed, load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target;
      if (el instanceof HTMLElement && el.closest("input, select, textarea, button, canvas, [contenteditable]")) return;
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
  const markers = info && tl ? eventsToMarkers(info.events ?? [], tl, info.started_utc) : [];
  const hasVideo = !!info?.visible?.file;
  const recordedH = info?.visible_alignment ? parseAlignment(info.visible_alignment).H : null;
  const overlayH = recordedH ?? loadAlignment(typeof localStorage !== "undefined" ? localStorage : null).H;
  const traces = seriesTraces(series, p.rois);

  const transport = (
    <span style={{ display: "flex", gap: 8, alignItems: "center", flex: "1 1 auto", minWidth: 0 }}>
      <button className="secondary" onClick={() => setIndex(0)} title="First frame" aria-label="First frame">⏮</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i - 1, n))} title="Previous frame" aria-label="Previous frame">◀︎</button>
      <button className="primary" style={{ minWidth: 64 }} onClick={() => setPlaying((v) => !v)}>{playing ? "pause" : "play"}</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i + 1, n))} title="Next frame" aria-label="Next frame">▶︎</button>
      <button className="secondary" onClick={() => setIndex(clampIndex(n - 1, n))} title="Last frame" aria-label="Last frame">⏭</button>
      <select value={String(speed)} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed">
        {SPEEDS.map((s) => <option key={String(s)} value={String(s)}>{speedLabel(s)}</option>)}
      </select>
      <input type="range" min={0} max={Math.max(n - 1, 0)} value={index} style={{ flex: "1 1 60px", minWidth: 60 }} aria-label="Timeline"
        aria-valuetext={`${t.toFixed(3)} s, frame ${index + 1} of ${n}`}
        onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }} />
      <b style={{ whiteSpace: "nowrap", textAlign: "right" }}>{t.toFixed(3)} s · {index + 1}/{n}</b>
    </span>
  );

  return (
    <StudioFrame layout={p.layout} topbar={p.topbar}
      strip={<ToolStrip tool={p.layout.tool} onTool={(tool) => p.dispatch({ type: "setTool", tool })} onCollapseAll={() => p.dispatch({ type: "collapseAll" })} zoom={p.layout.zoom} onZoom={(z) => p.dispatch({ type: "setZoom", zoom: z })}
        leading={<button title="Back to experiments" aria-label="Back to experiments" onClick={p.onBack}>←</button>} />}
      center={
        <div className={`center-split ${p.layout.visibleMode === "side" && hasVideo ? "on" : ""}`}>
          <ThermalView frame={frame} palette={p.palette} scaleMode={p.scaleMode} manual={p.manual} onScale={setShown}
            rois={p.rois.rois} selected={p.rois.selected} tool={p.layout.tool} zoom={p.layout.zoom} onRoi={p.roiDispatch} onStats={onStats}
            overlay={p.layout.visibleMode === "overlay" && hasVideo ? <VisibleVideo plain name={p.name} t={t} playing={playing} speed={speed} /> : undefined} overlayStyle={p.layout.overlay} overlayH={overlayH} />
          {p.layout.visibleMode === "side" && hasVideo && <VisibleVideo big name={p.name} t={t} playing={playing} speed={speed} measuredFps={info?.visible?.measured_fps} />}
        </div>
      }
      dock={
        <PlotDock title="temperature vs time (whole recording)" onCollapse={() => p.dispatch({ type: "toggle", panel: "dock" })}>
          <TimePlot traces={traces} markers={markers} window={{ t0: 0, t1: Math.max(info?.duration_s ?? 0, 0.001) }} cursorT={t}
            emptyText={p.rois.rois.length ? "loading series…" : "add a spot or rectangle ROI to plot it over the whole recording"}
            onSeek={(tt) => { if (tl) { setPlaying(false); setIndex(nearestIndex(tl.t_s, tt)); } }} />
        </PlotDock>
      }
      rail={
        <Rail>
          <RailSection title="experiment" open={p.layout.sections.experiment} onToggle={() => p.dispatch({ type: "toggleSection", section: "experiment" })}>
            <div className="kv">
              <span>name</span><span className="v plain" style={{ fontSize: 11 }}>{p.name}</span>
              <span>frames</span><span className="v plain">{n}</span>
              <span>duration</span><span className="v plain">{info ? `${info.duration_s.toFixed(2)} s` : "—"}</span>
              <span>status</span><span className="v plain">{info ? (info.complete ? "complete" : "INCOMPLETE") : "—"}</span>
              <span>format</span><span className="v plain">{info?.ir_format ?? "—"}</span>
              <span>case</span><span className="v">{active ? `${active.low_c?.toFixed(0)}…${active.high_c?.toFixed(0)} °C` : "—"}</span>
              <span>emissivity</span><span className="v">{fmtAny((cam.object_parameters as Record<string, unknown> | undefined)?.ObjectEmissivity)}</span>
            </div>
            <MetadataEditor name={p.name} experiment={exp} onSaved={() => { api.experiment(p.name).then(setInfo).catch((e) => setErr(String(e))); }} />
          </RailSection>
          <RailSection title="measurements" open={p.layout.sections.measurements} onToggle={() => p.dispatch({ type: "toggleSection", section: "measurements" })} tag="this frame">
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmtCelsius(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmtCelsius(hdr.min_c)}</span>
                <span>max</span><span className="v">{fmtCelsius(hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmtCelsius(hdr.mean_c)}</span>
                <span>frame id</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">loading…</div>}
            {info?.rois && info.rois.length > 0 && (
              <div className="row">
                <button className="secondary" onClick={() => { const parsed = loadRois({ getItem: () => JSON.stringify({ rois: info.rois, nextId: 1 }), setItem: () => undefined } as unknown as Storage); p.roiDispatch({ type: "replace", rois: parsed.rois as Roi[] }); }}>
                  load this recording's {info.rois.length} ROI{info.rois.length > 1 ? "s" : ""}
                </button>
                <span className="hint">as they were when it was recorded (exports/roi_series.csv matches them)</span>
              </div>
            )}
            <RoiRows rois={p.rois.rois} stats={stats} selected={p.rois.selected}
              dispatch={p.roiDispatch} />
            {err && <div className="errbox">{err}</div>}
          </RailSection>
          <RailSection title="display" open={p.layout.sections.display} onToggle={() => p.dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={p.palette} setPalette={p.setPalette} scaleMode={p.scaleMode} setScaleMode={p.setScaleMode} manual={p.manual} setManual={p.setManual} shown={shown} />
          </RailSection>
          <RailSection title="visible camera" open={p.layout.sections.visible} onToggle={() => p.dispatch({ type: "toggleSection", section: "visible" })} tag="recorded video">
            <VisiblePanel mode="playback" name={p.name} hasVideo={hasVideo} t={t} playing={playing} speed={speed} measuredFps={info?.visible?.measured_fps} visibleMode={p.layout.visibleMode} overlay={p.layout.overlay} dispatch={p.dispatch} aligned={!!overlayH} />
          </RailSection>
          <RailSection title="export" open={p.layout.sections.export} onToggle={() => p.dispatch({ type: "toggleSection", section: "export" })} tag="derived files">
            <ExportSection name={p.name} index={index} nFrames={n} rois={p.rois.rois} celsius={hdr?.kelvin_per_count != null} thermalPreview={info?.thermal_preview} />
          </RailSection>
        </Rail>
      }
      statusbar={<StatusBar status={p.status} recording={p.recording} left={transport} />}
    />
  );
}
