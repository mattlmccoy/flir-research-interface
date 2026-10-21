import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { api, type ExperimentInfo } from "../lib/api.ts";
import { ADJUST_LIMITS, NEUTRAL_ADJUST, clampAdjust, isNeutral, type VisibleAdjust } from "../lib/visibleAdjust.ts";
import { filterTableValues, parseRangeHeader, recordedAdjust, svgFilterId, type AdjustSource, type VisibleRange } from "../lib/visibleAdjustUi.ts";

/** One labelled range slider in a `.kv` grid (shared by the overlay registration and the adjustment). */
export function Slider({ label, value, min, max, step, unit, digits, signed = false, title, onChange }: { label: string; value: number; min: number; max: number; step: number; unit?: string; digits?: number; signed?: boolean; title?: string; onChange: (v: number) => void }) {
  const d = digits ?? (step < 1 ? 2 : 0);
  return (
    <label style={{ display: "contents" }} title={title}>
      <span>{label}</span>
      <span className="v plain" style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ width: 110 }} aria-label={label} />
        <span style={{ minWidth: 44, textAlign: "right" }}>{signed && value > 0 ? "+" : ""}{value.toFixed(d)}{unit ?? ""}</span>
      </span>
    </label>
  );
}

/** The SVG filter for an adjusted visible element plus the CSS `filter` that uses it. Neutral → no
 *  filter at all (nothing rendered, no `filter` property), so an unadjusted view is untouched. */
export function adjustFilter(a: Readonly<VisibleAdjust> | undefined): { svg: ReactNode; style: CSSProperties } {
  if (!a || isNeutral(a)) return { svg: null, style: {} };
  const id = svgFilterId(a);
  const { slope, intercept } = filterTableValues(a);
  const svg = (
    <svg width="0" height="0" aria-hidden="true" focusable="false" style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}>
      <filter id={id} colorInterpolationFilters="sRGB">
        <feComponentTransfer>
          <feFuncR type="linear" slope={slope} intercept={intercept} />
          <feFuncG type="linear" slope={slope} intercept={intercept} />
          <feFuncB type="linear" slope={slope} intercept={intercept} />
        </feComponentTransfer>
      </filter>
    </svg>
  );
  return { svg, style: { filter: `url(#${id})` } };
}

interface ControlsProps {
  value: VisibleAdjust;
  onChange: (a: VisibleAdjust) => void;
  onReset: () => void;
  resetLabel: string;
  resetDisabled?: boolean;
  /** Small text under the sliders (where the values come from, save state, range warning). */
  notes?: ReactNode;
}

/** Exposure / brightness / contrast sliders, the same for the live preview and a recorded run. */
export function VisibleAdjustControls({ value, onChange, onReset, resetLabel, resetDisabled, notes }: ControlsProps) {
  const set = (k: keyof VisibleAdjust) => (v: number) => onChange(clampAdjust({ ...value, [k]: v }));
  return (
    <>
      <div className="kv" aria-label="visible video adjustment">
        <Slider label="exposure" value={value.exposure_ev} min={ADJUST_LIMITS.exposure_ev[0]} max={ADJUST_LIMITS.exposure_ev[1]} step={0.1} digits={1} signed unit=" EV" onChange={set("exposure_ev")} title="Software gain in stops (display only; the camera's exposure is not changed). Pixels the camera stored as white stay white." />
        <Slider label="brightness" value={value.brightness} min={ADJUST_LIMITS.brightness[0]} max={ADJUST_LIMITS.brightness[1]} step={0.01} signed onChange={set("brightness")} title="Offset added to every pixel (fraction of full scale)" />
        <Slider label="contrast" value={value.contrast} min={ADJUST_LIMITS.contrast[0]} max={ADJUST_LIMITS.contrast[1]} step={0.05} unit="×" onChange={set("contrast")} title="Stretch around mid-grey" />
      </div>
      <div className="row">
        <button className="secondary" disabled={resetDisabled} onClick={onReset}>{resetLabel}</button>
        {notes}
      </div>
    </>
  );
}

export type SaveState = { state: "idle" } | { state: "saving" } | { state: "error"; error: string };
export interface RunAdjust { adjust: VisibleAdjust; source: AdjustSource; save: SaveState; set: (a: VisibleAdjust) => void; reset: () => void; }

const SAVE_DEBOUNCE_MS = 500;

/** A recorded run's visible adjustment: starts from the run's effective values, a slider move shows
 *  at once and saves the sidecar (debounced); reset deletes the sidecar and returns to the recorded
 *  values (or neutral). Writes go out in order; a pending save is sent when the run changes. */
export function useRunVisibleAdjust(name: string, info: ExperimentInfo | null): RunAdjust {
  const [cur, setCur] = useState<{ name: string; adjust: VisibleAdjust; source: AdjustSource } | null>(null);
  const [save, setSave] = useState<SaveState>({ state: "idle" });
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef<{ name: string; adjust: VisibleAdjust; timer: ReturnType<typeof setTimeout> } | null>(null);
  const ops = useRef(0);

  // Seed once per run (a later info refresh must not undo slider moves that are still being saved).
  useEffect(() => {
    if (!info || info.name !== name || cur?.name === name) return;
    const eff = info.visible_adjust;
    setCur({ name, adjust: clampAdjust(eff ?? NEUTRAL_ADJUST), source: eff?.source ?? "neutral" });
    setSave({ state: "idle" });
  }, [info, name, cur?.name]);

  function enqueue(op: () => Promise<unknown>): void {
    const n = ++ops.current;
    setSave({ state: "saving" });
    chain.current = chain.current.catch(() => undefined).then(op).then(
      () => { if (n === ops.current) setSave({ state: "idle" }); },
      (e: unknown) => { if (n === ops.current) setSave({ state: "error", error: String(e) }); },
    );
  }
  function flush(): void {
    const p = pending.current;
    if (!p) return;
    clearTimeout(p.timer);
    pending.current = null;
    enqueue(() => api.setVisibleAdjust(p.name, p.adjust));
  }
  useEffect(() => () => flush(), [name]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = cur && cur.name === name ? cur : null;
  return {
    adjust: shown?.adjust ?? NEUTRAL_ADJUST,
    source: shown?.source ?? "neutral",
    save,
    set: (a) => {
      if (!shown) return;
      const adjust = clampAdjust(a);
      setCur({ name, adjust, source: "sidecar" });
      if (pending.current) clearTimeout(pending.current.timer);
      setSave({ state: "saving" });
      pending.current = { name, adjust, timer: setTimeout(flush, SAVE_DEBOUNCE_MS) };
    },
    reset: () => {
      if (!shown) return;
      if (pending.current) { clearTimeout(pending.current.timer); pending.current = null; }
      const recorded = recordedAdjust(info?.name === name ? info.visible_adjust_recorded : null);
      setCur({ name, adjust: recorded ?? { ...NEUTRAL_ADJUST }, source: recorded ? "recorded" : "neutral" });
      enqueue(() => api.clearVisibleAdjust(name));
    },
  };
}

const rangeCache = new Map<string, Promise<VisibleRange | null>>();

/** What the visible video route actually serves for `url` (its X-Visible-Range header, asked once
 *  per URL); `fallback` (the info's prediction) only while unknown or when the header is unreadable. */
export function useVisibleRange(url: string | null, fallback: VisibleRange | null | undefined): VisibleRange | null {
  const [got, setGot] = useState<{ url: string; range: VisibleRange | null } | null>(null);
  useEffect(() => {
    if (!url) return;
    let live = true;
    let p = rangeCache.get(url);
    if (!p) {
      p = api.visibleRangeHeader(url).then(parseRangeHeader, () => null);
      rangeCache.set(url, p);
    }
    void p.then((range) => { if (live) setGot({ url, range }); });
    return () => { live = false; };
  }, [url]);
  const header = got && got.url === url ? got.range : null;
  return header ?? fallback ?? null;
}
