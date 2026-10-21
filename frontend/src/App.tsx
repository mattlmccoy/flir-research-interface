import { rangeFromRoi, saturationCount } from "./lib/enhance.ts";
import { saveSnapshot, snapshotFilename, snapshotFooter } from "./lib/snapshot.ts";
import { DeltaPicker } from "./components/DeltaPicker.tsx";
import { deltaTrace } from "./lib/delta.ts";
import { ProfilePanel, type FieldSnapshot } from "./components/ProfilePanel.tsx";
import { radiometryFromCamera } from "./lib/emissivity.ts";
import { useCallback, useEffect, useReducer, useRef, useState, useMemo } from "react";
import { api, operatorBase, type RecordingStatus, type Status } from "./lib/api.ts";
import { wsUrl } from "./lib/operator.ts";
import { decodeFrameMessage, type FrameMessage } from "./lib/protocol.ts";
import type { PaletteName } from "./lib/palette.ts";
import type { Range, ScaleMode } from "./lib/scale.ts";
import { DEFAULT_LAYOUT, layoutHasKey, layoutReducer, loadLayout, saveLayout } from "./lib/layout.ts";
import { usePresets } from "./lib/usePresets.ts";
import { displayFromView, presetMarker, startupRestore, thermalFromInfo, type ViewDisplay } from "./lib/presets.ts";
import { isNeutral } from "./lib/visibleAdjust.ts";
import { applyLivePreset, saveCurrentPreset } from "./lib/presetActions.ts";
import { PresetPicker, SaveCurrentAs } from "./components/PresetPicker.tsx";
import { EMPTY_ROIS, hasRois, loadRois, roiLabel, saveRois } from "./lib/roi.ts";
import { initHistory, roiHistoryReducer } from "./lib/roiHistory.ts";
import { TraceBuffer, WINDOWS, visibleWindow, windowLabel } from "./lib/plot.ts";
import { roiColor } from "./lib/overlay.ts";
import { fmtCelsius } from "./lib/format.ts";
import { ThermalView, type StatsMap } from "./components/ThermalView.tsx";
import { DisplayControls } from "./components/DisplayControls.tsx";
import { SetupPage } from "./components/SetupPage.tsx";
import { RecordPanel } from "./components/RecordPanel.tsx";
import { RoiRows } from "./components/RoiRows.tsx";
import { CameraControls } from "./components/CameraControls.tsx";
import { VisibleLive, VisiblePanel } from "./components/VisiblePanel.tsx";
import { AlignmentPanel } from "./components/AlignmentPanel.tsx";
import { PickLayer } from "./components/PickLayer.tsx";
import { EMPTY_ALIGNMENT, alignmentReducer, loadAlignment, parseAlignment, saveAlignment, serializeAlignment } from "./lib/alignment.ts";
import { TimePlot, type Trace } from "./components/TimePlot.tsx";
import { ExperimentsPage } from "./components/ExperimentsPage.tsx";
import { PlaybackPage } from "./components/PlaybackPage.tsx";
import { StudioFrame } from "./components/studio/StudioFrame.tsx";
import { ToolStrip } from "./components/studio/ToolStrip.tsx";
import { StripActions } from "./components/studio/StripActions.tsx";
import { Rail } from "./components/studio/Rail.tsx";
import { RailSection } from "./components/studio/RailSection.tsx";
import { PlotDock } from "./components/studio/PlotDock.tsx";
import { StatusBar } from "./components/studio/StatusBar.tsx";
import { LiveControlStrip } from "./components/LiveControlStrip.tsx";
import { useControlStatus } from "./lib/useControlStatus.ts";
import { LiveControl } from "./lib/liveControl.ts";
import { evalRateAlarm, loadRateAlarm, saveRateAlarm, slopeOver, type RateAlarmState } from "./lib/rate.ts";
import { RatePanel } from "./components/RatePanel.tsx";
import { MaskPanel } from "./components/MaskPanel.tsx";
import { rfNotchStatus } from "./lib/rfNotch.ts";
import { EMPTY_MASKS, hasMasks, loadMasks, maskPixels, maskedStats, masksAsRois, saveMasks, toolForMaskMode } from "./lib/mask.ts";
import { initMaskHistory, maskHistoryReducer, type MaskHistoryAction } from "./lib/maskHistory.ts";
import type { RoiAction } from "./lib/roi.ts";

type Page = "live" | "setup" | "experiments" | "playback";
const storage = (() => {
  try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; }
})();
/** Which preset-restorable layout parts this browser had stored when the page loaded, read once
 *  before any save (the App saves its layout on mount, which would make every part look stored). */
const STORED_AT_LOAD = { display: layoutHasKey(storage, "display"), visibleAdjust: layoutHasKey(storage, "visibleAdjust") };
/** ~10 min of live trace at 15 Hz per ROI. */
const MAX_TRACE_POINTS = 9000;

/** Three short tones: the heating-rate alarm (best effort; browsers may block audio until a click). */
function beep(): void {
  try {
    const AC = (globalThis as { AudioContext?: typeof AudioContext }).AudioContext;
    if (!AC) return;
    const ctx = new AC();
    for (let i = 0; i < 3; i++) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; g.gain.value = 0.15;
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + i * 0.25); o.stop(ctx.currentTime + i * 0.25 + 0.15);
    }
    setTimeout(() => { void ctx.close(); }, 1200);
  } catch { /* no audio */ }
}

export function App() {
  const [page, setPage] = useState<Page>("setup");
  const [openExp, setOpenExp] = useState<string | null>(null);
  const [openTitle, setOpenTitle] = useState<string | null>(null);  // display name, if renamed
  const [layout, dispatch] = useReducer(layoutReducer, DEFAULT_LAYOUT, () => loadLayout(storage));
  useEffect(() => { saveLayout(storage, layout); }, [layout]);
  const presets = usePresets();
  // Startup: each part this browser had nothing stored for (palette/range, visible sliders) starts
  // from the last applied preset. Nothing is sent to the camera. A part already changed while the
  // presets loaded is left alone.
  const restored = useRef(STORED_AT_LOAD.display && STORED_AT_LOAD.visibleAdjust);
  useEffect(() => {
    if (restored.current || !presets.doc) return;
    restored.current = true;
    const r = startupRestore({ displayWasStored: STORED_AT_LOAD.display, visibleWasStored: STORED_AT_LOAD.visibleAdjust, lastApplied: presets.lastApplied, currentView: layout.display });
    if (r.display && JSON.stringify(layout.display) === JSON.stringify(DEFAULT_LAYOUT.display)) dispatch({ type: "setDisplay", patch: r.display });
    if (r.visible && isNeutral(layout.visibleAdjust)) dispatch({ type: "setVisibleAdjust", adjust: r.visible });
  }, [presets.doc]); // eslint-disable-line react-hooks/exhaustive-deps
  const [roiHist, roiDispatch] = useReducer(roiHistoryReducer, EMPTY_ROIS, () => initHistory(loadRois(storage)));
  const rois = roiHist.present;
  const maskModeRef = useRef(false);
  const maskDispatchRef = useRef<(a: MaskHistoryAction) => void>(() => undefined);
  // Cmd/Ctrl+Z undoes an ROI edit; Cmd/Ctrl+Y or Cmd/Ctrl+Shift+Z redoes. Text fields keep their own undo.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const k = e.key.toLowerCase();
      const undo = k === "z" && !e.shiftKey, redo = k === "y" || (k === "z" && e.shiftKey);
      if (!undo && !redo) return;
      const el = e.target;
      if (el instanceof HTMLElement && (el.isContentEditable || el.tagName === "TEXTAREA"
        || (el instanceof HTMLInputElement && !["range", "checkbox", "radio", "button", "color"].includes(el.type)))) return;
      e.preventDefault();
      // in mask mode the shortcut undoes mask edits; otherwise ROI edits
      if (maskModeRef.current) maskDispatchRef.current({ type: undo ? "undo" : "redo" });
      else roiDispatch({ type: undo ? "undo" : "redo" });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  // ROIs are scoped so each experiment keeps its own set; live shares one "live" scope.
  const roiScope = page === "playback" && openExp ? `exp.${openExp}` : "live";
  const roiScopeRef = useRef(roiScope);
  useEffect(() => {
    if (roiScopeRef.current === roiScope) return;
    roiScopeRef.current = roiScope;
    roiDispatch({ type: "load", rois: loadRois(storage, roiScope).rois });
  }, [roiScope]);
  // Persist to the active scope. Never create an empty experiment scope from the transient load —
  // PlaybackPage seeds a run from its own stored ROIs the first time it is opened.
  useEffect(() => {
    const scope = roiScopeRef.current;
    if (scope !== "live" && rois.rois.length === 0 && !hasRois(storage, scope)) return;
    saveRois(storage, rois, scope);
  }, [rois]);
  // Mirror the live ROIs to the operator so the closed-loop temperature feed
  // (GET /api/live/roi-temps, polled by the RF controller) can measure them. The UI is the only
  // holder of the on-screen ROIs; debounced so a drag doesn't spam the endpoint. Live scope only.
  useEffect(() => {
    if (roiScope !== "live") return;
    const t = setTimeout(() => { api.putLiveRois(rois.rois).catch(() => {}); }, 400);
    return () => clearTimeout(t);
  }, [rois.rois, roiScope]);
  // Region masks follow the ROI scopes (live / exp.<name>); they only pick the pixels behind the
  // colour auto-range and the frame stats. A run's stored masks are seeded by PlaybackPage.
  const [maskHist, maskDispatch] = useReducer(maskHistoryReducer, EMPTY_MASKS, () => initMaskHistory(loadMasks(storage, roiScope)));
  const masks = maskHist.present;
  const [maskMode, setMaskMode] = useState(false);
  maskModeRef.current = maskMode;
  maskDispatchRef.current = maskDispatch;
  const maskScopeRef = useRef(roiScope);
  useEffect(() => {
    if (maskScopeRef.current === roiScope) return;
    maskScopeRef.current = roiScope;
    const loaded = loadMasks(storage, roiScope);
    maskDispatch({ type: "load", shapes: loaded.shapes });
    maskDispatch({ type: "setEnabled", enabled: loaded.enabled });
    maskDispatch({ type: "setDrawMode", mode: loaded.drawMode });
  }, [roiScope]);
  useEffect(() => {
    const scope = maskScopeRef.current;  // never create an empty run scope before PlaybackPage seeds it
    if (scope !== "live" && masks.shapes.length === 0 && !hasMasks(storage, scope)) return;
    saveMasks(storage, masks, scope);
  }, [masks]);
  // In mask mode the image's editing layer works on the mask regions (ROI handles, move, Delete).
  const maskRois = useMemo(() => masksAsRois(masks.shapes), [masks.shapes]);
  const maskEdit = useCallback((a: RoiAction) => maskDispatch({ type: "edit", action: a }), []);
  const toggleMaskMode = (on: boolean) => {
    setMaskMode(on);
    if (on && toolForMaskMode(layout.tool) !== layout.tool) dispatch({ type: "setTool", tool: toolForMaskMode(layout.tool) });
  };
  const [align, alignDispatch] = useReducer(alignmentReducer, EMPTY_ALIGNMENT, () => loadAlignment(storage));
  useEffect(() => { saveAlignment(storage, align); }, [align]);
  const [calibrating, setCalibrating] = useState(false);
  // adopt the operator's stored alignment when this browser has none
  useEffect(() => {
    if (align.H) return;
    api.getAlignment().then((doc) => { const a = parseAlignment(doc); if (a.H) alignDispatch({ type: "adopt", state: a }); }).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function saveAlignmentToOperator(): Promise<string> {
    try {
      await api.putAlignment(serializeAlignment(align));
    } catch (e) {
      const msg = String(e);
      if (/Failed to fetch|404/.test(msg)) throw new Error("the running operator does not have the alignment endpoint yet (restart it on the latest build); the alignment is kept in this browser meanwhile");
      throw e;
    }
    return "saved on the operator; future recordings carry it";
  }

  const [status, setStatus] = useState<Status>({ state: "disconnected" });
  const [recording, setRecording] = useState<RecordingStatus | null>(null);
  const [frame, setFrame] = useState<FrameMessage | null>(null);
  // palette and colour range live in the layout (remembered by the browser, restorable from a preset)
  const { palette, scaleMode, manual } = layout.display;
  const setPalette = useCallback((p: PaletteName) => dispatch({ type: "setDisplay", patch: { palette: p } }), []);
  const setScaleMode = useCallback((m: ScaleMode) => dispatch({ type: "setDisplay", patch: { scaleMode: m } }), []);
  const setManual = useCallback((r: Range) => dispatch({ type: "setDisplay", patch: { manual: r } }), []);
  const setView = useCallback((v: ViewDisplay) => dispatch({ type: "setDisplay", patch: v }), []);
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
  const nowTRef = useRef(0);
  // RF power, closed-loop setpoint and RF ON/OFF edges from the linked RF controller (CXN panel),
  // drawn on the live plot against the ROI temperatures.
  const liveCtl = useRef(new LiveControl());
  const ctlStatus = useControlStatus(1000);
  useEffect(() => { liveCtl.current.ingest(ctlStatus, nowTRef.current); }, [ctlStatus]);
  // Heating-rate alarm: per-ROI max traces feed the rate (the plot shows means).
  const maxBuffers = useRef(new Map<number, TraceBuffer>());
  const [rateCfg, setRateCfg] = useState(() => loadRateAlarm(storage));
  useEffect(() => { saveRateAlarm(storage, rateCfg); }, [rateCfg]);
  const rateCfgRef = useRef(rateCfg);
  rateCfgRef.current = rateCfg;
  const [rates, setRates] = useState<Map<number, number | null>>(new Map());
  const onStats = useCallback((m: StatsMap, f: FrameMessage) => {
    if (t0Ref.current === null) t0Ref.current = f.header.device_timestamp_ns;
    const t = (f.header.device_timestamp_ns - t0Ref.current) / 1e9;
    nowTRef.current = t;
    for (const [id, s] of m) {
      let b = buffers.current.get(id);
      if (!b) { b = new TraceBuffer(MAX_TRACE_POINTS); buffers.current.set(id, b); }
      if (b.lastT !== t) b.push(t, s.mean);
      let bm = maxBuffers.current.get(id);
      if (!bm) { bm = new TraceBuffer(MAX_TRACE_POINTS); maxBuffers.current.set(id, bm); }
      if (bm.lastT !== t) bm.push(t, s.max);
    }
    for (const id of Array.from(buffers.current.keys())) if (!m.has(id)) buffers.current.delete(id);
    for (const id of Array.from(maxBuffers.current.keys())) if (!m.has(id)) maxBuffers.current.delete(id);
    const rc = rateCfgRef.current;
    const src = rc.stat === "max" ? maxBuffers.current : buffers.current;
    const next = new Map<number, number | null>();
    for (const [id, b] of src) next.set(id, slopeOver(b, rc.windowS));
    setRates(next);
    setLiveStats(m);
  }, []);
  const alarmRef = useRef<RateAlarmState>({ tripped: false, roi: null, rate: null });
  const [alarmLatched, setAlarmLatched] = useState<RateAlarmState | null>(null);
  const recordingRef = useRef(false);
  useEffect(() => {
    const prev = alarmRef.current;
    const next = evalRateAlarm(rates, rateCfg, prev);
    alarmRef.current = next;
    if (next.tripped && !prev.tripped) {
      setAlarmLatched(next);
      if (rateCfg.beep) beep();
      if (rateCfg.mark && recordingRef.current) {
        const r = rois.rois.find((x) => x.id === next.roi);
        void api.recordingEvent("rate alarm", `${r ? roiLabel(r) : "ROI"} ${next.rate?.toFixed(2)} °C/s ≥ ${rateCfg.threshold} °C/s (${rateCfg.stat}, ${rateCfg.windowS} s)`).catch(() => undefined);
      }
    } else if (next.tripped) {
      setAlarmLatched((l) => (l && next.rate !== null && next.rate > (l.rate ?? -Infinity) ? { ...l, rate: next.rate } : l));
    }
  }, [rates, rateCfg]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshInfo = useCallback(() => { api.info().then(setInfo).catch(() => undefined); }, []);
  const [field, setField] = useState<FieldSnapshot | null>(null);
  const maskPx = useMemo(() => (masks.enabled && field ? maskPixels(masks.shapes, field.w, field.h) : null), [masks.enabled, masks.shapes, field?.w, field?.h]); // eslint-disable-line react-hooks/exhaustive-deps
  const maskUsed = useMemo(() => (maskPx ? maskPx.reduce((n, v) => n + v, 0) : null), [maskPx]);
  const maskStats = maskPx && field ? maskedStats(field.c, maskPx) : null;
  const [reference, setReference] = useState<Float32Array | null>(null);
  const rad = useMemo(() => radiometryFromCamera(info), [info]);
  const refresh = useCallback(async () => {
    try { setStatus(await api.status()); } catch { setStatus({ state: "unreachable" }); }
    try { setRecording(await api.recordingStatus()); } catch { /* keep last */ }
  }, []);
  useEffect(() => { void refresh(); const id = setInterval(refresh, 1000); return () => clearInterval(id); }, [refresh]);

  useEffect(() => {
    if (status.state !== "acquiring") return;
    let alive = true;
    // with the RF-banding filter on, the operator adds a display copy of each frame
    const ws = new WebSocket(wsUrl(operatorBase(), layout.rfNotch ? "/ws/frames?rf_notch=1" : "/ws/frames"));
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
    refreshInfo();
    return () => { alive = false; ws.close(); };
  }, [status.state, refreshInfo, layout.rfNotch]);

  const stale = status.state === "acquiring" && lastFrameAt > 0 && performance.now() - lastFrameAt > 2000;
  const dot = status.state === "acquiring" && !stale ? "live" : status.state === "error" ? "err"
    : status.state === "disconnected" ? "" : "warn";

  async function disconnect() {
    await api.disconnect();
    setFrame(null);
    buffers.current.clear();
    maxBuffers.current.clear();
    liveCtl.current.clear();
    t0Ref.current = null;
    await refresh();
    setPage("setup");
  }

  const hdr = frame?.header;
  const cam = info ?? {};
  const active = cam.active_case as { low_c?: number; high_c?: number } | undefined;
  const isRecording = recording?.state === "recording";
  recordingRef.current = isRecording;
  const visibleAvailable = recording?.visible?.state !== "unavailable";
  const nearLimit = hdr && active && hdr.max_c != null && active.high_c != null && hdr.max_c > active.high_c - 10;
  const allHidden = !layout.rail && !layout.dock;
  const [revealNote, setRevealNote] = useState<string | null>(null);

  // Presets (live): apply writes camera settings only on this click, never while recording.
  const cameraConnected = status.state === "connected" || status.state === "acquiring";
  const liveThermal = cameraConnected && info ? thermalFromInfo(info).values : null;
  const saveCurrent = (name: string) => saveCurrentPreset(name, { visible: layout.visibleAdjust, view: layout.display, currentThermal: api.currentThermal, put: presets.put });
  const livePicker = (
    <PresetPicker store={presets} mode="live" onSaveCurrent={saveCurrent}
      marker={(p) => presetMarker({ visible: layout.visibleAdjust, display: displayFromView(layout.display), thermal: liveThermal }, p)}
      onApply={(p) => applyLivePreset(p, {
        recording: isRecording, cameraConnected, view: layout.display,
        readRecording: async () => (await api.recordingStatus()).state === "recording",
        setVisible: (adjust) => dispatch({ type: "setVisibleAdjust", adjust }), setView,
        readInfo: api.info, setParameters: api.setParameters, confirm: (m) => window.confirm(m),
        markApplied: presets.markApplied, onCameraWritten: refreshInfo,
      })} />
  );

  const nowT = hdr && t0Ref.current !== null ? (hdr.device_timestamp_ns - t0Ref.current) / 1e9 : 0;
  const traces: Trace[] = rois.rois.flatMap((r, i) => {
    if (r.hidden) return []; // hidden on the image = hidden on the plot (still measured + recorded)
    const b = buffers.current.get(r.id);
    return [{ id: r.id, label: roiLabel(r), color: roiColor(r, i), t: b?.t ?? [], v: b?.v ?? [] }];
  });
  const withDelta = (() => {
    const d = layout.delta;
    if (!d) return traces;
    const a = traces.find((x) => x.id === d.a), b = traces.find((x) => x.id === d.b);
    return a && b ? [...traces, deltaTrace(a, b)] : traces;
  })();

  // PNG snapshot of the live view (thermal + overlays), same as the display-controls camera button.
  // snapshots say "RF banding removed" only when the shown frame really had banding taken out
  const rfInfo = frame?.header.display?.rf_notch;
  const rfFiltered = layout.rfNotch && !!frame?.display && !!rfInfo && rfInfo.applied && rfInfo.bands.length > 0;
  const saveLiveImage = () => {
    const v = document.querySelector<HTMLElement>(".view");
    if (v) saveSnapshot(v, snapshotFilename("live", null, null, { rfFiltered }), snapshotFooter({ name: "live", tS: null, index: null, range: shown, palette, rois: rois.rois.length, reference: !!reference, rfFiltered }));
  };

  const topbar = (
    <>
      <span className="wordmark">FLIR RESEARCH INTERFACE</span>
      <nav className="tabs">
        <button className={page === "live" ? "active" : ""} aria-current={page === "live" ? "page" : undefined} onClick={() => setPage("live")}>live</button>
        <button className={page === "experiments" || page === "playback" ? "active" : ""} aria-current={page === "experiments" || page === "playback" ? "page" : undefined} onClick={() => setPage("experiments")}>experiments</button>
        <button className={page === "setup" ? "active" : ""} aria-current={page === "setup" ? "page" : undefined} onClick={() => setPage("setup")}>setup</button>
      </nav>
      {page === "playback" && openExp && (
        <span className="crumb">
          <button className="secondary" onClick={() => setPage("experiments")} title="Back to the experiments list" aria-label="Back to experiments">← experiments</button>
          <span className="open-name" title={openTitle ? `${openTitle} — folder ${openExp}` : openExp}>{openTitle || openExp}</span>
          <button className="secondary" title="Show this run's folder in Finder / Explorer" aria-label="Reveal run folder"
            onClick={() => { setRevealNote(null); api.reveal(openExp).then((r) => { if (!r.ok) setRevealNote(r.error ?? "reveal failed"); }).catch((e) => setRevealNote(String(e))); }}>reveal</button>
          {revealNote && <span className="bad" role="alert">{revealNote}</span>}
        </span>
      )}
      <span className="conn">
        <span className={`dot ${dot}`} />
        <span className="who">{status.device ? `${status.device.model} · ${status.device.serial}` : "no camera"}</span>
        <span>· {stale ? "no frames" : status.state}</span>
        {status.state !== "disconnected" && status.state !== "unreachable" && <button className="secondary" onClick={disconnect}>disconnect</button>}
      </span>
    </>
  );

  const rateBadge = alarmLatched
    ? <button type="button" className="badge rec" onClick={() => dispatch({ type: "openSection", section: "measurements" })} title="Heating-rate alarm tripped. Click to open it in the measurements panel.">RATE ALARM {alarmLatched.rate?.toFixed(1)} °C/s</button>
    : null;
  const statusbar = <StatusBar status={status} recording={recording} displayFps={wsFps} stale={stale} extra={page === "live" ? <>{rateBadge}<LiveControlStrip /></> : undefined} />;

  if (page === "setup") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<SetupPage onConnected={() => { void refresh(); setPage("live"); }} />} />;
  }
  if (page === "experiments") {
    return <StudioFrame layout={layout} page topbar={topbar} statusbar={statusbar}
      center={<ExperimentsPage onOpen={(name, title) => { setOpenExp(name); setOpenTitle(title ?? null); setPage("playback"); }}/>} />;
  }
  if (page === "playback" && openExp) {
    return <PlaybackPage name={openExp} layout={layout} dispatch={dispatch} topbar={topbar}
      rois={rois} roiDispatch={roiDispatch} masks={masks} maskDispatch={maskDispatch} maskMode={maskMode} onMaskMode={toggleMaskMode}
      palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode}
      manual={manual} setManual={setManual} onBack={() => setPage("experiments")} status={status} recording={recording} presets={presets} />;
  }

  return (
    <StudioFrame layout={layout} topbar={topbar} dispatch={dispatch} statusbar={statusbar}
      strip={<ToolStrip tool={layout.tool} onCollapseAll={() => dispatch({ type: allHidden ? "restoreAll" : "collapseAll" })} collapsed={allHidden} zoom={layout.zoom} onZoom={(z) => dispatch({ type: "setZoom", zoom: z })} maskMode={maskMode} onMaskMode={toggleMaskMode}
        onTool={(t) => dispatch({ type: "setTool", tool: t })}
        extras={<StripActions
          onSaveImage={saveLiveImage} saveDisabled={!frame}
          roisHidden={layout.roisHidden} onToggleRois={() => dispatch({ type: "toggleRois" })}
          hasVisible={visibleAvailable} visibleOverlayOn={layout.visibleMode === "overlay"}
          onToggleVisible={() => dispatch({ type: "setVisibleMode", mode: layout.visibleMode === "overlay" ? "rail" : "overlay" })}
          overlayOpacity={layout.overlay.opacity} onOverlayOpacity={(v) => dispatch({ type: "setOverlay", patch: { opacity: v } })}
          visibleTip="No visible camera configured for live overlay"
          palette={palette} setPalette={setPalette} />} />}
      center={
        <div className={`center-split ${(layout.visibleMode === "side" || calibrating) && visibleAvailable ? "on" : ""}`}>
          <ThermalView frame={frame} palette={palette} scaleMode={scaleMode} manual={manual} onScale={setShown} setManual={setManual} setScaleMode={setScaleMode}
            rois={maskMode ? maskRois : rois.rois} statsRois={rois.rois} selected={maskMode ? masks.selected : rois.selected} selectedIds={maskMode ? masks.selectedIds : rois.selectedIds} tool={layout.tool} roisHidden={!maskMode && layout.roisHidden} labelScope={maskMode ? `${roiScope}.mask` : roiScope} zoom={layout.zoom} onRoi={maskMode ? maskEdit : roiDispatch} onStats={onStats} rad={rad} extremes={layout.extremes} isotherm={layout.isotherm} onField={setField} reference={reference} hold={layout.hold} flipH={layout.flipH} flipV={layout.flipV} agc={layout.agc} filter={layout.filter} units={layout.units} useDisplay={layout.rfNotch} valid={layout.segment.on ? { min: layout.segment.min, max: layout.segment.max } : null} mask={maskPx} maskShapes={masks.enabled || maskMode ? masks.shapes : []} maskMode={maskMode} onMask={maskDispatch}
            overlay={layout.visibleMode === "overlay" && !calibrating && visibleAvailable ? <VisibleLive plain adjust={layout.visibleAdjust} /> : undefined} overlayStyle={layout.overlay} overlayH={align.H}
            topLayer={calibrating ? <PickLayer label="IR" flipH={layout.flipH} flipV={layout.flipV} color="var(--live)" points={align.pairs.map((p) => p.ir)} pending={align.pending?.ir} onPick={(p) => alignDispatch({ type: "pick", side: "ir", p })} /> : undefined} />
          {(layout.visibleMode === "side" || calibrating) && visibleAvailable && (
            <VisibleLive big flipH={layout.flipH} flipV={layout.flipV} adjust={layout.visibleAdjust} topLayer={calibrating ? <PickLayer label="visible" flipH={layout.flipH} flipV={layout.flipV} color="var(--accent)" points={align.pairs.map((p) => p.visible)} pending={align.pending?.visible} onPick={(p) => alignDispatch({ type: "pick", side: "visible", p })} /> : undefined} />
          )}
        </div>
      }
      dock={
        <PlotDock onCollapse={() => dispatch({ type: "toggle", panel: "dock" })}
          controls={
            <select value={String(liveWindow)} onChange={(e) => setLiveWindow(Number(e.target.value))} aria-label="Plot time window">
              {WINDOWS.map((w) => <option key={String(w)} value={String(w)}>{windowLabel(w)}</option>)}
            </select>
          }>
          <TimePlot traces={[...withDelta, ...liveCtl.current.leftTraces()]} rightTraces={liveCtl.current.rightTraces()} rightUnits="W" markers={liveCtl.current.markers} window={visibleWindow(nowT, liveWindow, 0)} emptyText="add a spot or rectangle ROI to plot its temperature" />
        </PlotDock>
      }
      rail={
        <Rail>
          <RailSection id="measurements" title="measurements" open={layout.sections.measurements} onToggle={() => dispatch({ type: "toggleSection", section: "measurements" })} tag={maskPx ? `masked · ${(maskUsed ?? 0).toLocaleString()} px` : undefined}>
            {hdr ? (
              <div className="kv">
                <span>center</span><span className="v">{fmtCelsius(hdr.center_c)}</span>
                <span>min</span><span className="v">{fmtCelsius(maskPx ? maskStats?.min ?? null : hdr.min_c)}</span>
                <span>max</span><span className="v">{fmtCelsius(maskPx ? maskStats?.max ?? null : hdr.max_c)}</span>
                <span>mean</span><span className="v">{fmtCelsius(maskPx ? maskStats?.mean ?? null : hdr.mean_c)}</span>
                {!!hdr.over_range && <><span>over-range</span><span className="v" style={{ textAlign: "right" }}><span className="badge warn" title="Pixels the camera could not represent (scene hotter than its range) — saturated or 16-bit wrapped. Shown magenta and excluded from the stats. Switch the camera to a higher measurement range.">{hdr.over_range} px</span></span></>}
                <span>ir format</span><span className="v plain">{hdr.ir_format}</span>
                <span>frame</span><span className="v plain">{hdr.frame_id}</span>
              </div>
            ) : <div className="muted">waiting for frames…</div>}
            {hdr && hdr.kelvin_per_count === null && <div className="errbox">Stream is not temperature-linear; raw counts only.</div>}
            {nearLimit && <div className="warnbox">Max within 10 °C of the range limit ({active?.high_c} °C).</div>}
            <RoiRows rois={rois.rois} units={layout.units} conv={field?.conv ?? null} stats={liveStats} selected={rois.selected} selectedIds={rois.selectedIds} extremes={layout.extremes} onExtremes={(on) => dispatch({ type: "setExtremes", on })}
              dispatch={roiDispatch} />
            <MaskPanel state={masks} dispatch={maskDispatch} maskMode={maskMode} onMaskMode={toggleMaskMode} usedPx={maskUsed} frame={field ? { w: field.w, h: field.h } : null} />
            <DeltaPicker rois={rois.rois} delta={layout.delta} onChange={(delta) => dispatch({ type: "setDelta", delta })} />
            <RatePanel rois={rois.rois} rates={rates} cfg={rateCfg} onCfg={setRateCfg} latched={alarmLatched} onAck={() => setAlarmLatched(null)} />
          </RailSection>
          <RailSection id="profile" title="profile & histogram" open={layout.sections.profile} onToggle={() => dispatch({ type: "toggleSection", section: "profile" })} tag="current frame">
            <ProfilePanel field={field} rois={rois.rois} selected={rois.selected} shown={shown} />
          </RailSection>
          <RailSection id="camera" title="camera" open={layout.sections.camera} onToggle={() => dispatch({ type: "toggleSection", section: "camera" })} tag={isRecording ? "locked during recording" : "writes camera nodes"}>
            <CameraControls info={info} locked={isRecording} onApplied={refreshInfo} presetSave={<SaveCurrentAs store={presets} onSave={saveCurrent} label="save current as preset…" />} />
          </RailSection>
          <RailSection id="recording" title="recording" open={layout.sections.recording} onToggle={() => dispatch({ type: "toggleSection", section: "recording" })}>
            <RecordPanel acquiring={status.state === "acquiring"} rois={rois.rois} liveAdjust={layout.visibleAdjust} lastApplied={presets.lastApplied} masks={masks.enabled && masks.shapes.length ? masks.shapes : null} />
          </RailSection>
          <RailSection id="display" title="display" open={layout.sections.display} onToggle={() => dispatch({ type: "toggleSection", section: "display" })} tag="visualization only">
            <DisplayControls palette={palette} setPalette={setPalette} scaleMode={scaleMode} setScaleMode={setScaleMode} manual={manual} setManual={setManual} shown={shown} isotherm={layout.isotherm} setIsotherm={(isotherm) => dispatch({ type: "setIsotherm", isotherm })} hasReference={!!reference} onSetReference={() => { if (field) setReference(new Float32Array(field.c)); }} onClearReference={() => setReference(null)} onRangeFromRoi={(() => { const sel = rois.rois.find((r) => r.id === rois.selected); if (!field || !sel || sel.kind === "spot") return null; return () => { const rg = rangeFromRoi(field.c, field.w, field.h, sel); if (rg) { setManual({ min: Math.floor(rg.min * 10) / 10, max: Math.ceil(rg.max * 10) / 10 }); setScaleMode("manual"); } }; })()} hold={layout.hold} setHold={(hold) => dispatch({ type: "setHold", hold })} flipH={layout.flipH} flipV={layout.flipV} setFlip={(h, v) => dispatch({ type: "setFlip", h, v })} agc={layout.agc} setAgc={(agc) => dispatch({ type: "setAgc", agc })} units={layout.units} setUnits={(units) => dispatch({ type: "setUnits", units })} conv={field?.conv ?? null} filter={layout.filter} setFilter={(filter) => dispatch({ type: "setFilter", filter })} rfNotch={layout.rfNotch} setRfNotch={(on) => dispatch({ type: "setRfNotch", on })} rfStatus={rfNotchStatus(layout.rfNotch, frame?.header.display?.rf_notch)} segment={layout.segment} setSegment={(segment) => dispatch({ type: "setSegment", segment })} saturation={(() => { const cs = (info as Record<string, unknown> | null | undefined)?.active_case as { low_c?: number; high_c?: number } | undefined; if (!field || !cs || typeof cs.low_c !== "number" || typeof cs.high_c !== "number") return null; const n = saturationCount(field.c, { low: cs.low_c, high: cs.high_c }); return { ...n, lowC: cs.low_c, highC: cs.high_c }; })()} onSnapshot={saveLiveImage} />
          </RailSection>
          <RailSection id="visible" title="visible camera" open={layout.sections.visible} onToggle={() => dispatch({ type: "toggleSection", section: "visible" })} tag="preview only">
            <VisiblePanel mode="live" picker={livePicker} available={visibleAvailable} reason={recording?.visible?.reason} adjust={layout.visibleAdjust} visibleMode={layout.visibleMode} overlay={layout.overlay} dispatch={dispatch} aligned={!!align.H} />
            {visibleAvailable && <AlignmentPanel state={align} dispatch={alignDispatch} calibrating={calibrating} onCalibrating={setCalibrating} irSize={hdr ? [hdr.width, hdr.height] : null} onSave={saveAlignmentToOperator} onFinishOverlay={() => { setCalibrating(false); dispatch({ type: "setVisibleMode", mode: "overlay" }); }} />}
          </RailSection>
        </Rail>
      }
    />
  );
}
