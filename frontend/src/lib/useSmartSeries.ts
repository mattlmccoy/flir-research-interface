// Loads a recorded run's stored smart ROI series (one per smart ROI) and runs the compute job for
// a ROI that has none or a stale one (POST …/compute, poll …/status). Pure logic: smartSeries.ts.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { SMART_POLL_MS, isNotFound, parseSmartSeries, smartPollStep, type SmartJob, type SmartPollEvent, type SmartPollState, type SmartSeriesState } from "./smartSeries.ts";

/** Points per stored series fetched for the plot and the playhead readout (the API strides down). */
export const SMART_SERIES_POINTS = 4000;

export interface SmartSeriesHook {
  states: Map<number, SmartSeriesState>;
  jobs: Map<number, SmartJob>;
  /** Bumped after a compute finishes (pass to useSmartPlaybackOverlays so outlines refresh). */
  version: number;
  compute: (id: number) => void;
  reload: (id: number) => void;
}

/** `beforeCompute` runs first (e.g. save the on-screen ROIs into the run); false cancels. */
export function useSmartSeries(name: string, ids: number[], beforeCompute: (id: number) => Promise<boolean>, onError: (msg: string) => void): SmartSeriesHook {
  const [states, setStates] = useState<Map<number, SmartSeriesState>>(new Map());
  const [jobs, setJobs] = useState<Map<number, SmartJob>>(new Map());
  const [version, setVersion] = useState(0);
  const gen = useRef(0);  // bumped per run (and unmount): late responses of an old run are dropped
  const polling = useRef(new Set<number>());
  const idsKey = ids.join(",");

  const setState = (id: number, st: SmartSeriesState) => setStates((m) => new Map(m).set(id, st));
  const setJob = (id: number, jb: SmartJob) => setJobs((m) => new Map(m).set(id, jb));

  const load = useCallback((id: number, g: number): Promise<SmartSeriesState> => {
    setState(id, { kind: "loading" });
    return api.smartSeries(name, id, SMART_SERIES_POINTS)
      .then((raw): SmartSeriesState => {
        const s = parseSmartSeries(raw);
        return s ? { kind: "ready", series: s } : { kind: "error", message: "the operator returned a malformed smart ROI series" };
      })
      .catch((e: unknown): SmartSeriesState => (isNotFound(e) ? { kind: "missing" } : { kind: "error", message: String(e) }))
      .then((st) => { if (gen.current === g) setState(id, st); return st; });
  }, [name]);

  const poll = useCallback(async (id: number, g: number, start: SmartJob | null): Promise<void> => {
    const active = polling.current;  // this run's set (replaced when the run changes)
    if (active.has(id)) return;
    active.add(id);
    try {
      let ps: SmartPollState = { job: start, failures: 0 };
      let delay = SMART_POLL_MS;
      for (;;) {
        await new Promise((r) => setTimeout(r, delay));
        if (gen.current !== g) return;
        const ev: SmartPollEvent = await api.smartStatus(name, id)
          .then((job): SmartPollEvent => ({ ok: true, job }), (e: unknown): SmartPollEvent => ({ ok: false, error: String(e) }));
        if (gen.current !== g) return;
        const step = smartPollStep(ps, ev);
        ps = step.next;
        if (ps.job) setJob(id, ps.job);
        if (step.action === "reload") { await load(id, g); setVersion((v) => v + 1); }
        if (step.action !== "continue") return;
        delay = step.delayMs;
      }
    } finally {
      active.delete(id);
    }
  }, [name, load]);

  useEffect(() => {
    const g = ++gen.current;
    polling.current = new Set();
    setStates(new Map()); setJobs(new Map());
    for (const id of ids) {
      // a series not there yet may be computing already (post-stop job, a regenerate): show it
      void load(id, g).then((st) => {
        if (st.kind !== "missing" && !(st.kind === "ready" && st.series.stale)) return;
        api.smartStatus(name, id).then((jb) => {
          if (gen.current !== g) return;
          setJob(id, jb);
          if (jb.state === "running") void poll(id, g, jb);
        }).catch(() => undefined);
      });
    }
    return () => { gen.current++; };
  }, [name, idsKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  const compute = useCallback((id: number) => {
    const g = gen.current;
    void (async () => {
      try {
        if (!(await beforeCompute(id)) || gen.current !== g) return;
        const jb = await api.smartCompute(name, id);
        setJob(id, jb);
        void poll(id, g, jb);
      } catch (e) {
        if (gen.current === g) onError(`smart ROI ${id} compute: ${String(e)}`);
      }
    })();
  }, [name, beforeCompute, poll, onError]);

  const reload = useCallback((id: number) => { void load(id, gen.current); }, [load]);

  return { states, jobs, version, compute, reload };
}
