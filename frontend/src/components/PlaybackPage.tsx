import { rangeFromRoi, saturationCount } from "../lib/enhance.ts";
import { saveSnapshot, snapshotFilename, snapshotFooter } from "../lib/snapshot.ts";
import { DeltaPicker } from "../components/DeltaPicker.tsx";
import { deltaTrace } from "../lib/delta.ts";
import { ProfilePanel, type FieldSnapshot } from "../components/ProfilePanel.tsx";
import { radiometryFromCamera } from "../lib/emissivity.ts";
import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import type { Dispatch, ReactNode } from "react";
import { api, type ExperimentInfo, type RecordingStatus, type RoiSeries, type Status, type Timeline } from "../lib/api.ts";
import { type FrameMessage, decodeFrameBlock } from "../lib/protocol.ts";
import type { PaletteName } from "../lib/palette.ts";
import type { Range, ScaleMode } from "../lib/scale.ts";
import type { LayoutAction, LayoutState } from "../lib/layout.ts";
import { SPEEDS, clampIndex, nextFrameDelayMs, speedLabel } from "../lib/playback.ts";
import { loadRois, roiLabel, roisDifferFromStored, type Roi, type RoiAction, type RoiState } from "../lib/roi.ts";
import { roiColor } from "../lib/overlay.ts";
import { eventsToMarkers, nearestIndex, nextMarkerTime } from "../lib/events.ts";
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
    if (r.hidden) return []; // hidden on the image = hidden on the plot
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
  const inflight = useRef(new Map<number, Promise<void>>());
  const BLOCK = 60;
  const n = info?.n_frames ?? 0;
  const onStats = useCallback((m: StatsMap) => setStats(m), []);

  useEffect(() => {
    cache.current.clear();
    inflight.current.clear();
    Promise.all([api.experiment(p.name), api.timeline(p.name)])
      .then(([i, t]) => { setInfo(i); setTl(t); setIndex(0); }).catch((e) => setErr(String(e)));
  }, [p.name]);

  // Whole-recording ROI series from the backend; debounced so a drag does not fire per pixel.
  useEffect(() => {
    if (!info || p.rois.rois.length === 0) { setSeries(null); return; }
    let alive = true;
    const id = window.setTimeout(() => {
      api.series(p.name, p.rois.rois, p.layout.segment.on ? { min: p.layout.segment.min, max: p.layout.segment.max } : null, 800).then((s) => { if (alive) setSeries(s); }).catch((e) => { if (alive) setErr(String(e)); });
    }, 250);
    return () => { alive = false; window.clearTimeout(id); };
  }, [p.name, info, p.rois.rois, p.layout.segment.on, p.layout.segment.min, p.layout.segment.max]);

  const ensureBlock = useCallback((start: number): Promise<void> => {
    const running = inflight.current.get(start);
    if (running) return running;
    const promise = api.frameBlock(p.name, start, BLOCK)
      .then((buf) => {
        for (const m of decodeFrameBlock(buf)) {
          const idx = (m.header as { index?: number }).index;
          if (typeof idx === "number") cache.current.set(idx, m);
        }
        // keep the cache bounded to a few blocks around the play head
        if (cache.current.size > BLOCK * 4) {
          const keys = [...cache.current.keys()].sort((a, b) => a - b);
          for (const k of keys.slice(0, keys.length - BLOCK * 3)) cache.current.delete(k);
        }
      })
      .finally(() => { inflight.current.delete(start); });
    inflight.current.set(start, promise);
    return promise;
  }, [p.name]);

  const load = useCallback(async (i: number): Promise<FrameMessage> => {
    const hit = cache.current.get(i);
    if (hit) return hit;
    await ensureBlock(Math.floor(i / BLOCK) * BLOCK);
    const m = cache.current.get(i);
    if (!m) throw new Error(`frame ${i} not returned`);
    return m;
  }, [ensureBlock]);

  useEffect(() => {
    if (!info || n === 0) return;
    let alive = true;
    load(index).then((m) => { if (alive) setFrame(m); }).catch((e) => setErr(String(e)));
    // prefetch the next block once we're into the current one, so playback never waits
    const blockStart = Math.floor(index / BLOCK) * BLOCK;
    if (index - blockStart >= BLOCK - 20 && blockStart + BLOCK < n) void ensureBlock(blockStart + BLOCK).catch(() => undefined);
    return () => { alive = false; };
  }, [index, info, n, load, ensureBlock]);

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
  const [field, setField] = useState<FieldSnapshot | null>(null);
  const [reference, setReference] = useState<Float32Array | null>(null);
  const rad = useMemo(() => radiometryFromCamera(info?.camera), [info]);
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;
  const markers = info && tl ? eventsToMarkers(info.events ?? [], tl, info.started_utc) : [];
  const hasVideo = !!info?.visible?.file;
  const recordedH = info?.visible_alignment ? parseAlignment(info.visible_alignment).H : null;
  const overlayH = recordedH ?? loadAlignment(typeof localStorage !== "undefined" ? localStorage : null).H;
  const traces = seriesTraces(series, p.rois);
  // Derived files (ROI plot, peak frames, ROI video, roi_series.csv) are stale when the ROIs on
  // screen no longer match the ones stored with the recording; badge the export section so it's
  // visible even when collapsed.
  const derivedStale = roisDifferFromStored(p.rois.rois, info?.rois ?? null);
  const withDelta = (() => {
    const d = p.layout.delta;
    if (!d) return traces;
    const a = traces.find((x) => x.id === d.a), b = traces.find((x) => x.id === d.b);
    return a && b ? [...traces, deltaTrace(a, b)] : traces;
  })();

  const transport = (
    <span style={{ display: "flex", gap: 8, alignItems: "center", flex: "1 1 auto", minWidth: 0 }}>
      <button className="secondary" onClick={() => setIndex(0)} title="First frame" aria-label="First frame">⏮</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i - 1, n))} title="Previous frame" aria-label="Previous frame">◀︎</button>
      <button className="primary" style={{ minWidth: 64 }} onClick={() => setPlaying((v) => !v)}>{playing ? "pause" : "play"}</button>
      <button className="secondary" onClick={() => setIndex((i) => clampIndex(i + 1, n))} title="Next frame" aria-label="Next frame">▶︎</button>
      <button className="secondary" onClick={() => setIndex(clampIndex(n - 1, n))} title="Last frame" aria-label="Last frame">⏭</button>
      <button className="secondary" disabled={!markers.length} onClick={() => { const mt = nextMarkerTime(markers, t, -1); if (mt !== null && tl) { setPlaying(false); setIndex(nearestIndex(tl.t_s, mt)); } }} title="Previous mark (RF ON/OFF, NUC, gap…)" aria-label="Previous mark">◆◀︎</button>
      <button className="secondary" disabled={!markers.length} onClick={() => { const mt = nextMarkerTime(markers, t, 1); if (mt !== null && tl) { setPlaying(false); setIndex(nearestIndex(tl.t_s, mt)); } }} title="Next mark" aria-label="Next mark">▶︎◆</button>
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
    <StudioFrame layout={p.layout} topbar={p.topbar} dispatch={p.dispatch} dockFoot={transport}
      strip={<ToolStrip tool={p.layout.tool} onTool={(tool) => p.dispatch({ type: "setTool", tool })} onCollapseAll={() => p.dispatch({ type: !p.layout.rail && !p.layout.dock ? "restoreAll" : "collapseAll" })} collapsed={!p.layout.rail && !p.layout.dock} zoom={p.layout.zoom} onZoom={(z) => p.dispatch({ type: "setZoom", zoom: z })} />}
      center={
        <div className={`center-split ${p.layout.visibleMode === "side" && hasVideo ? "on" : ""}`}>
          <ThermalView frame={frame} palette={p.palette} scaleMode={p.scaleMode} manual={p.manual} onScale={setShown} setManual={p.setManual} setScaleMode={p.setScaleMode}
            rois={p.rois.rois} selected={p.rois.selected} selectedIds={p.rois.selectedIds} tool={p.layout.tool} zoom={p.layout.zoom} onRoi={p.roiDispatch} onStats={onStats} rad={rad} extremes={p.layout.extremes} isotherm={p.layout.isotherm} onField={setField} reference={reference} hold={p.layout.hold} flipH={p.layout.flipH} flipV={p.layout.flipV} agc={p.layout.agc} filter={p.layout.filter} units={p.layout.units} valid={p.layout.segment.on ? { min: p.layout.segment.min, max: p.layout.segment.max } : null}
            overlay={p.layout.visibleMode === "overlay" && hasVideo ? <VisibleVideo plain name={p.name} t={t} playing={playing} speed={speed} /> : undefined} overlayStyle={p.layout.overlay} overlayH={overlayH} />
          {p.layout.visibleMode === "side" && hasVideo && <VisibleVideo big flipH={p.layout.flipH} flipV={p.layout.flipV} name={p.name} t={t} playing={playing} speed={speed} measuredFps={info?.visible?.measured_fps} />}
        </div>
      }
      dock={
        <PlotDock title="temperature vs time (whole recording)" foot={transport} onCollapse={() => p.dispatch({ type: "toggle", panel: "dock" })}>
          <TimePlot traces={withDelta} markers={markers} window={{ t0: 0, t1: Math.max(info?.duration_s ?? 0, 0.001) }} cursorT={t}
            emptyText={p.rois.rois.length ? "loading series…" : "add a spot or rectangle ROI to plot it over the whole recording"}
            onSeek={(tt) => { if (tl) { setPlaying(false); setIndex(nearestIndex(tl.t_s, tt)); } }} />
        </PlotDock>
      }
      rail={
        <Rail>
          <RailSection id="profile" title="profile & histogram" open={p.layout.sections.profile} onToggle={() => p.dispatch({ type: "toggleSection", section: "profile" })} tag="current frame">
            <ProfilePanel field={field} rois={p.rois.rois} selected={p.rois.selected} shown={shown} />
          </RailSection>
          <RailSection id="experiment" title="experiment" open={p.layout.sections.experiment} onToggle={() => p.dispatch({ type: "toggleSection", section: "experiment" })}>
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
          <RailSection id="measurements" title="measurements" open={p.layout.sections.measurements} onToggle={() => p.dispatch({ type: "toggleSection", section: "measurements" })} tag="this frame">
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
            <RoiRows rois={p.rois.rois} units={p.layout.units} conv={field?.conv ?? null} stats={stats} selected={p.rois.selected} selectedIds={p.rois.selectedIds} extremes={p.layout.extremes} onExtremes={(on) => p.dispatch({ type: "setExtremes", on })}
              dispatch={p.roiDispatch} />
            <DeltaPicker rois={p.rois.rois} delta={p.layout.delta} onChange={(delta) => p.dispatch({ type: "setDelta", delta })} />
            {err && <div className="errbox">{err}</div>}
          </RailSection>
          <RailSection id="display" title="display" open={p.layout.sections.display} onToggle={() => p.dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={p.palette} setPalette={p.setPalette} scaleMode={p.scaleMode} setScaleMode={p.setScaleMode} manual={p.manual} setManual={p.setManual} shown={shown} isotherm={p.layout.isotherm} setIsotherm={(isotherm) => p.dispatch({ type: "setIsotherm", isotherm })} hasReference={!!reference} onSetReference={() => { if (field) setReference(new Float32Array(field.c)); }} onClearReference={() => setReference(null)} onRangeFromRoi={(() => { const sel = p.rois.rois.find((r) => r.id === p.rois.selected); if (!field || !sel || sel.kind === "spot") return null; return () => { const rg = rangeFromRoi(field.c, field.w, field.h, sel); if (rg) { p.setManual({ min: Math.floor(rg.min * 10) / 10, max: Math.ceil(rg.max * 10) / 10 }); p.setScaleMode("manual"); } }; })()} hold={p.layout.hold} setHold={(hold) => p.dispatch({ type: "setHold", hold })} flipH={p.layout.flipH} flipV={p.layout.flipV} setFlip={(h, v) => p.dispatch({ type: "setFlip", h, v })} agc={p.layout.agc} setAgc={(agc) => p.dispatch({ type: "setAgc", agc })} units={p.layout.units} setUnits={(units) => p.dispatch({ type: "setUnits", units })} conv={field?.conv ?? null} filter={p.layout.filter} setFilter={(filter) => p.dispatch({ type: "setFilter", filter })} segment={p.layout.segment} setSegment={(segment) => p.dispatch({ type: "setSegment", segment })} saturation={(() => { const cs = (info?.camera as Record<string, unknown> | null | undefined)?.active_case as { low_c?: number; high_c?: number } | undefined; if (!field || !cs || typeof cs.low_c !== "number" || typeof cs.high_c !== "number") return null; const n = saturationCount(field.c, { low: cs.low_c, high: cs.high_c }); return { ...n, lowC: cs.low_c, highC: cs.high_c }; })()} onSnapshot={() => { const v = document.querySelector<HTMLElement>(".view"); if (v) saveSnapshot(v, snapshotFilename(p.name, index, t), snapshotFooter({ name: p.name, tS: t, index: index, range: shown, palette: p.palette, rois: p.rois.rois.length, reference: !!reference })); }} />
          </RailSection>
          <RailSection id="visible" title="visible camera" open={p.layout.sections.visible} onToggle={() => p.dispatch({ type: "toggleSection", section: "visible" })} tag="recorded video">
            <VisiblePanel mode="playback" name={p.name} hasVideo={hasVideo} t={t} playing={playing} speed={speed} measuredFps={info?.visible?.measured_fps} visibleMode={p.layout.visibleMode} overlay={p.layout.overlay} dispatch={p.dispatch} aligned={!!overlayH} />
          </RailSection>
          <RailSection id="export" title="export" open={p.layout.sections.export} onToggle={() => p.dispatch({ type: "toggleSection", section: "export" })} tag={derivedStale ? "update needed" : "derived files"} tagWarn={derivedStale}>
            <ExportSection name={p.name} index={index} nFrames={n} rois={p.rois.rois} celsius={hdr?.kelvin_per_count != null} thermalPreview={info?.thermal_preview} files={info?.exports ?? []} storedRois={info?.rois ?? null} onRefresh={() => { api.experiment(p.name).then(setInfo).catch((e) => setErr(String(e))); }} />
          </RailSection>
        </Rail>
      }
      statusbar={<StatusBar status={p.status} recording={p.recording} left={<span className="muted">playback</span>} />}
    />
  );
}
