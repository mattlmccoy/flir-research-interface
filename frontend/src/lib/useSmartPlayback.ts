// Playback's smart ROI wiring: the stored series + compute jobs (useSmartSeries), the per-frame
// stored outlines (useSmartPlaybackOverlays), the rail rows, the stale set and the plot traces.
// Pure logic lives in smartSeries.ts / smartTraces.ts; this only connects it to PlaybackPage.
import { createElement, useCallback, useMemo, useRef } from "react";
import { api, type ExperimentInfo } from "./api.ts";
import { roiColor } from "./overlay.ts";
import { roiLabel, type Roi } from "./roi.ts";
import { saveSmartForCompute, smartComputeAction, smartEdited, smartJobText, smartPlaybackRow } from "./smartSeries.ts";
import { smartTraces, type SmartDimChoice, type SmartTrace } from "./smartTraces.ts";
import type { SmartOverlay } from "./smartLabels.ts";
import { useSmartPlaybackOverlays } from "./useSmartPlaybackOverlays.ts";
import { useSmartSeries, type SmartSeriesHook } from "./useSmartSeries.ts";
import { smartPrefs, type SmartViewPrefs } from "./smartView.ts";
import { SmartComputeCell } from "../components/SmartComputeCell.tsx";
import type { SmartPlaybackRow } from "../components/RoiRows.tsx";

interface Args {
  name: string;
  rois: Roi[];
  info: ExperimentInfo | null;
  setInfo: (i: ExperimentInfo) => void;
  setErr: (m: string) => void;
  /** Index of the frame on screen (null: none yet); the outline and readout follow it. */
  shown: number | null;
  /** Playhead index, used for the readout only while no frame is on screen. */
  index: number;
  show: { sample: boolean; rings: boolean };
  sizeDim: Exclude<SmartDimChoice, "off">;
  /** Ring bands switched off per ROI (layout.smartView): left out of the plot. */
  view: SmartViewPrefs;
}

export interface SmartPlayback {
  smartIds: number[];
  smart: SmartSeriesHook;
  /** Stored outlines of the frame on screen (none until the run's smart series is computed). */
  overlays: SmartOverlay[];
  /** Await before showing frame `index` so it and its outline appear together. */
  ensureOverlays: (index: number) => Promise<void>;
  /** Abort overlay fetches that hold none of these frame indices. */
  retainOverlays: (indexes: number[]) => void;
  /** Ids whose stored series no longer matches the ROI (stored or on screen): drawn muted. */
  stale: Set<number>;
  rows: Map<number, SmartPlaybackRow>;
  /** Lines from the stored series (the strided series path skips smart ROIs). */
  plot: SmartTrace[];
}

export function useSmartPlayback({ name, rois, info, setInfo, setErr, shown, index, show, sizeDim, view }: Args): SmartPlayback {
  const smartIds = useMemo(() => rois.filter((r) => r.kind === "smart").map((r) => r.id), [rois]);
  // A compute reads the ROI stored with the run, so an unsaved or edited smart ROI is saved first:
  // only that ROI is written into the run's stored set (same id replaced, else appended). The info
  // refresh is awaited and kept in a ref, so a second compute right after builds on that save.
  const infoRef = useRef(info);
  infoRef.current = info;
  const beforeCompute = useCallback(async (id: number): Promise<boolean> => {
    const r = rois.find((x) => x.id === id);
    const cur = infoRef.current;
    if (!cur) { setErr("run info not loaded yet; try again"); return false; }
    if (!r || r.kind !== "smart") return false;
    const got = await saveSmartForCompute(r, cur, {
      confirm: (m) => window.confirm(m),
      putRois: (list) => api.putRois(name, list),
      refresh: () => api.experiment(name),
    });
    infoRef.current = got.info;
    if (got.info !== cur) setInfo(got.info);
    return got.ok;
  }, [name, rois, setErr, setInfo]);
  const smart = useSmartSeries(name, smartIds, beforeCompute, setErr);
  const { overlays, ensure: ensureOverlays, retain: retainOverlays } = useSmartPlaybackOverlays(name, smartIds, shown, smart.version);
  const at = shown ?? index;
  const stale = useMemo(() => new Set(rois.flatMap((r) => {
    const st = smart.states.get(r.id);
    return r.kind === "smart" && st?.kind === "ready" && (st.series.stale || smartEdited(r, info?.rois)) ? [r.id] : [];
  })), [rois, smart.states, info?.rois]);
  const rows = useMemo(() => {
    const m = new Map<number, SmartPlaybackRow>();
    for (const r of rois) {
      if (r.kind !== "smart") continue;
      const st = smart.states.get(r.id) ?? { kind: "loading" as const };
      const job = smart.jobs.get(r.id) ?? null;
      const edited = smartEdited(r, info?.rois);
      const act = smartComputeAction(st, job, edited);
      const text = smartJobText(job);
      m.set(r.id, {
        // the exact frame's stored state (overlay) gates the number when the series is downsampled
        view: smartPlaybackRow(st, at, { edited, overlay: overlays.find((o) => o.id === r.id) ?? null }),
        action: act || text ? createElement(SmartComputeCell, {
          label: roiLabel(r), act, job, text,
          onAct: () => (act?.kind === "reload" ? smart.reload(r.id) : smart.compute(r.id)),
        }) : null,
      });
    }
    return m;
  }, [rois, smart.states, smart.jobs, smart.compute, smart.reload, at, info?.rois, overlays]);  // eslint-disable-line react-hooks/exhaustive-deps
  const plot = rois.flatMap((r, i) => {
    const st = smart.states.get(r.id);
    if (r.kind !== "smart" || r.hidden || st?.kind !== "ready") return [];
    const isStale = st.series.stale || smartEdited(r, info?.rois);
    return smartTraces(st.series, { ...show, dims: sizeDim, hiddenRings: smartPrefs(view, `exp.${name}`, r.id).hiddenRings }, { id: r.id, label: roiLabel(r), color: roiColor(r, i), stale: isStale });
  });
  return { smartIds, smart, overlays, ensureOverlays, retainOverlays, stale, rows, plot };
}
