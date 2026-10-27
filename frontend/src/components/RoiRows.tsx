import { NumberField } from "./NumberField.tsx";
import { convertTemp, fmtTemp, type Conversion, type Units } from "../lib/units.ts";
import { useEffect, useState, type ReactNode } from "react";
import { roiId, roiLabel, type Roi, type RoiAction, type RoiStats, loadRois } from "../lib/roi.ts";
import { COLOR_PRESETS, roiColor } from "../lib/overlay.ts";
import { Disclosure } from "./Disclosure.tsx";
import { parseRingOffsets } from "../lib/smartSettings.ts";
import { smartRowView, type SmartFeed, type SmartFrameOverlay, type SmartRowView } from "../lib/smartFeed.ts";
import { SMART_FEED_INTERVAL_MS } from "../lib/useSmartFeed.ts";
import { smartDetails } from "../lib/smartReadout.ts";
import { smartPrefs, type SmartRowPrefs, type SmartViewPrefs } from "../lib/smartView.ts";
import type { LayoutAction } from "../lib/layout.ts";

interface Props {
  units?: Units; conv?: Conversion | null;
  /** Hot/cold marker toggle (undefined hides the button). */
  extremes?: boolean; onExtremes?: (on: boolean) => void;
  rois: Roi[];
  stats: Map<number, RoiStats>;
  selected: number | null; selectedIds?: number[];
  dispatch: (a: RoiAction) => void;
  /** Live: the operator's smart ROI readouts (null = feed not running). Playback: omitted. */
  smartFeed?: SmartFeed | null;
  /** Live: the frame on screen's smart overlays (WS header `smart`): their `over` block gives the
   *  bounded numbers while pixels are over range (lib/smartFeed.ts smartRowView). */
  smartOverlays?: readonly SmartFrameOverlayWithId[] | null;
  /** Playback: each smart ROI's readout at the playhead from its stored series, plus its compute
   *  control (lib/smartSeries.ts smartPlaybackRow). Takes precedence over `smartFeed`. */
  smartPlayback?: Map<number, SmartPlaybackRow>;
  /** Per smart ROI: row expanded, ring bands hidden (browser layout state, display only). */
  smartView?: SmartViewPrefs;
  onSmartView?: (a: SmartViewAction) => void;
  /** Scope of these ROIs, as labelScope: "live" or "exp.<run name>" (keys `smartView`). */
  scope?: string;
}
export type SmartViewAction = Extract<LayoutAction, { type: "toggleSmartExpanded" | "toggleSmartRing" }>;
export interface SmartPlaybackRow { view: SmartRowView; action: ReactNode; }

type SmartRoi = Extract<Roi, { kind: "smart" }>;
type SmartFrameOverlayWithId = SmartFrameOverlay & { id: number };
const overlayOf = (list: readonly SmartFrameOverlayWithId[] | null | undefined, id: number) => list?.find((o) => o.id === id) ?? null;

/** Value column of a smart row: the operator's mean (never a client-side number) while the feed is
 *  fresh and the entry valid; holding is marked and warn-coloured so it never reads as locked. */
function SmartValue({ id, feed, overlays, played, units, conv }: { id: number; feed: SmartFeed | null | undefined; overlays?: readonly SmartFrameOverlayWithId[] | null; played?: SmartPlaybackRow; units: Units; conv: Conversion | null }) {
  if (feed === undefined && !played) return <span className="vals">…</span>;
  const v = played ? played.view : smartRowView(feed ?? null, id, Date.now(), SMART_FEED_INTERVAL_MS, overlayOf(overlays, id));
  if (v.mean === null) return <span className={`vals smart-val tone-${v.tone}`} title={v.tone === "over" ? smartMarkerTip(v.marker ?? "") : undefined}>{v.marker ?? "n/a"}</span>;
  return <span className={`vals smart-val tone-${v.tone}`} title={v.marker ? smartMarkerTip(v.marker) : undefined}>{v.marker ? `${v.marker} · ` : ""}{fmtTemp(v.mean, units, conv)}</span>;
}

/** Hover text for the value column's marker(s). */
function smartMarkerTip(marker: string): string {
  const tips: string[] = [];
  if (marker.includes("stale")) tips.push("stale: the ROI or recording changed since this series was computed; recompute it");
  if (marker.includes("≈")) tips.push("≈ nearest stored point: the plot series is downsampled");
  if (marker.includes("holding")) tips.push("holding the last good outline (edge lost this frame)");
  if (marker.includes("over range")) tips.push("some sample pixels are over the camera's range: the mean is a lower bound (they are counted at the range top), the min is exact, the max is above the range");
  return tips.join(" · ");
}

/** Ring band toggles ("5 · 10 · 25 px"): a hidden band is not drawn, read out or plotted. Display
 *  only: tracking, the stored series, CSV and the TC-POWER feed keep every band. */
function RingChips({ r, hidden, onToggle }: { r: SmartRoi; hidden: readonly number[]; onToggle: (px: number) => void }) {
  if (!r.rings_px.length) return null;
  return (
    <div className="smart-rings" role="group" aria-label={`ring bands shown for ${roiLabel(r)}`}>
      <span className="muted">rings</span>
      {r.rings_px.map((px) => {
        const on = !hidden.includes(px);
        return <button key={px} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on} aria-label={`ring band to ${px} px`} onClick={() => onToggle(px)}
          title={`${on ? "Hide" : "Show"} the band out to ${px} px on the image, readout and plot (display only; tracking and the stored series are unchanged)`}>{px}</button>;
      })}
      <span className="muted">px</span>
    </div>
  );
}

/** Second line of a smart row: one summary line (state, mean, max, area); the chevron expands a
 *  compact table (sample, shown rings, size, sharpness, change, centroid) and the ring toggles. */
function SmartLines({ r, scope, feed, overlays, played, prefs, onView }: { r: SmartRoi; scope: string; feed: SmartFeed | null | undefined; overlays?: readonly SmartFrameOverlayWithId[] | null; played?: SmartPlaybackRow; prefs: SmartRowPrefs; onView?: (a: SmartViewAction) => void }) {
  if (feed === undefined && !played) return null;
  const v = played ? played.view : smartRowView(feed ?? null, r.id, Date.now(), SMART_FEED_INTERVAL_MS, overlayOf(overlays, r.id));
  const open = prefs.expanded && !!onView;
  const details = open && v.entry ? smartDetails(v.entry, prefs.hiddenRings) : [];
  return (
    <div className={`roi-stats smart-readout state-${v.tone}`} title={played ? "Smart ROI values at the frame on screen, from the series the operator computed and stored with this run. Size is measured from the thermal edge: read it with the edge sharpness." : "Smart ROI values from the operator. Size is measured from the thermal edge, which also moves when heat spreading blurs the boundary: read it with the edge sharpness."}>
      <div className="smart-head">
        {onView && <button type="button" className="smart-chevron" aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} the details of ${roiLabel(r)}`}
          onClick={() => onView({ type: "toggleSmartExpanded", scope, id: r.id })}>{open ? "▾" : "▸"}</button>}
        <span className="smart-summary">{v.summary}</span>
      </div>
      {open && <>
        <RingChips r={r} hidden={prefs.hiddenRings} onToggle={(px) => onView({ type: "toggleSmartRing", scope, id: r.id, px })} />
        {details.length > 0 && (
          <table className="smart-details"><tbody>
            {details.map((d) => <tr key={d.label}><th scope="row">{d.label}</th><td>{d.value}</td></tr>)}
          </tbody></table>
        )}
        {v.notes.map((n) => <div key={n} className="smart-note">{n}</div>)}
      </>}
      {played?.action}
    </div>
  );
}

function SmartEditor({ r, dispatch }: { r: SmartRoi; dispatch: (a: RoiAction) => void }) {
  const [rings, setRings] = useState<string | null>(null);  // draft while typing
  const [ringErr, setRingErr] = useState<string | null>(null);
  // "fixed" chosen but no °C typed yet; dropped whenever the stored rule changes (undo, load, reset)
  const [pendingFixed, setPendingFixed] = useState(false);
  useEffect(() => { setPendingFixed(false); }, [r.rule, r.id]);
  const set = (patch: Omit<Extract<RoiAction, { type: "setSmart" }>, "type" | "id">) => dispatch({ type: "setSmart", id: r.id, ...patch });
  const commitRings = () => {
    if (rings === null) return;
    const got = parseRingOffsets(rings);
    if (got.ok) { set({ rings_px: got.rings }); setRings(null); setRingErr(null); } else setRingErr(got.error);
  };
  const fixed = r.rule === "fixed" || pendingFixed;
  return (
    <div className="optics smart-settings">
      <div className="optics-title">Smart ROI · {roiLabel(r)}</div>
      <div className="optics-grid">
        <label htmlFor={`rings-${r.id}`}>rings</label>
        <input id={`rings-${r.id}`} type="text" value={rings ?? r.rings_px.join(", ")} aria-label={`ring offsets of ${roiLabel(r)} in px`} aria-invalid={!!ringErr}
          onChange={(e) => { setRings(e.target.value); setRingErr(null); }} onBlur={commitRings}
          onKeyDown={(e) => { if (e.key === "Enter") commitRings(); if (e.key === "Escape") { setRings(null); setRingErr(null); } }} />
        <span className="optics-unit" title="Band boundaries outside the sample edge, comma separated: 5, 10, 25 measures bands 0–5, 5–10 and 10–25 px.">px</span>

        <label htmlFor={`rule-${r.id}`}>edge rule</label>
        <select id={`rule-${r.id}`} value={fixed ? "fixed" : "relative"} aria-label={`edge rule of ${roiLabel(r)}`}
          onChange={(e) => { const f = e.target.value === "fixed"; setPendingFixed(f); if (!f) set({ rule: "relative" }); }}>
          <option value="relative">relative</option>
          <option value="fixed">fixed °C</option>
        </select>
        <span className="optics-unit" title="Relative: the edge sits between the surroundings and the sample core, re-estimated each frame. Fixed: the edge is one isotherm (recommended for comparing size with CAD).">?</span>

        {fixed && <>
          <label htmlFor={`fixed-${r.id}`}>edge at</label>
          <NumberField id={`fixed-${r.id}`} step={1} value={r.rule === "fixed" ? r.fixed_c ?? null : null} placeholder="°C" aria-label={`fixed edge temperature of ${roiLabel(r)} in °C`} onChange={(n) => set({ rule: "fixed", fixed_c: n })} />
          <span className="optics-unit" title="The isotherm that defines the edge, in the sample's corrected °C. Until a value is entered the relative rule stays in use.">°C</span>
        </>}

        <label htmlFor={`sens-${r.id}`}>sensitivity</label>
        <input id={`sens-${r.id}`} type="range" min={0.3} max={0.7} step={0.05} value={r.sensitivity} disabled={r.rule === "fixed"} aria-label={`sensitivity of ${roiLabel(r)}`}
          onChange={(e) => set({ sensitivity: Number(e.target.value) })} />
        <span className="optics-unit" title="Relative rule: where the edge sits between the surroundings (0.3, a wider outline) and the sample core (0.7, a tighter one).">{r.sensitivity.toFixed(2)}</span>

        <label htmlFor={`reps-${r.id}`}>ring ε</label>
        <NumberField id={`reps-${r.id}`} min={0.01} max={1} step={0.01} value={r.ring_emissivity ?? null} placeholder="sample's" aria-label={`ring emissivity of ${roiLabel(r)}`} onChange={(n) => set({ ring_emissivity: n })} />
        <span className="optics-unit" title="Emissivity for the rings (they measure the powder). Blank: the same as the sample. Applies to recorded runs; live readings use the camera setting, like every live ROI.">ε</span>
      </div>
      {ringErr && <div className="smart-error" role="alert">{ringErr}</div>}
      <div className="optics-foot">
        Changing these restarts tracking (the % change baseline resets).{" "}
        {r.ring_emissivity !== undefined && <button type="button" className="secondary" onClick={() => set({ ring_emissivity: null })} title="Rings use the sample's emissivity again">Reset ring ε</button>}
      </div>
    </div>
  );
}

function Values({ s, units, conv }: { s: RoiStats | undefined; units: Units; conv: Conversion | null }) {
  if (!s) return <span className="vals">…</span>;
  if (s.n === 0 || s.mean === null) return <span className="vals">n/a</span>;
  return <span className="vals">{fmtTemp(s.mean, units, conv)}</span>;
}

/** Second line under an area ROI: min · max · σ · pixel count (full width, never overlaps the name). */
function StatsLine({ r, s, units, conv }: { r: Roi; s: RoiStats | undefined; units: Units; conv: Conversion | null }) {
  if (!s || s.n === 0 || s.mean === null || r.kind === "spot") return null;
  const f = (v: number) => (units === "counts" ? fmtTemp(v, units, conv) : convertTemp(v, units, conv).toFixed(2));
  const sd = s.std !== undefined ? (units === "F" ? (s.std * 9 / 5).toFixed(2) : units === "counts" && conv ? String(Math.round(s.std / conv.kelvin_per_count)) : s.std.toFixed(2)) : null;
  return (
    <small className="roi-stats">
      min {f(s.min as number)} · max {f(s.max as number)}{sd !== null ? ` · σ ${sd}` : ""} · {s.n} px{s.excluded ? ` (${s.excluded} excluded)` : ""}
    </small>
  );
}

function where(r: Roi): string {
  switch (r.kind) {
    case "spot": return `spot x ${r.x} y ${r.y}`;
    case "rect": return `rect x ${r.x0}…${r.x1 - 1} y ${r.y0}…${r.y1 - 1} (${r.x1 - r.x0}×${r.y1 - r.y0} px)`;
    case "circle": return `circle centre (${r.cx}, ${r.cy}) r ${r.r.toFixed(1)} px`;
    case "ellipse": return `ellipse centre (${r.cx}, ${r.cy}) rx ${r.rx} ry ${r.ry} px`;
    case "line": return `line (${r.x0}, ${r.y0}) → (${r.x1}, ${r.y1})`;
    case "polygon": return `polygon with ${r.points.length} vertices`;
    case "polyline": return `spline with ${r.points.length} vertices`;
    case "smart": return `smart ROI, search outline of ${r.search.length} vertices`;
  }
}

function ColorPicker({ r, i, dispatch, onDone }: { r: Roi; i: number; dispatch: (a: RoiAction) => void; onDone: () => void }) {
  const current = roiColor(r, i);
  return (
    <div className="swatches" role="group" aria-label={`color of ${roiLabel(r)}`}>
      {COLOR_PRESETS.map((c) => (
        <button key={c} type="button" className={current.toLowerCase() === c ? "on" : ""} style={{ background: c }} title={c}
          onClick={() => { dispatch({ type: "recolor", id: r.id, color: c }); onDone(); }} />
      ))}
      <input type="color" aria-label="custom color" value={r.color ?? "#ffffff"} title="any color"
        onChange={(e) => dispatch({ type: "recolor", id: r.id, color: e.target.value })} />
      {r.kind === "spot" && (
        <label className="hint" style={{ flexBasis: "100%", marginTop: 4 }} title="Measurement cursor: report the mean of the 3×3 pixels around the spot (standard thermography practice) instead of the single pixel">
          <input type="checkbox" checked={r.box === 3} onChange={(e) => dispatch({ type: "setBox", id: r.id, box: e.target.checked ? 3 : 1 })} /> 3×3 average
        </label>
      )}
    </div>
  );
}

function OpticsEditor({ r, dispatch }: { r: Roi; dispatch: (a: RoiAction) => void }) {
  const set = (patch: { emissivity?: number | null; reflected_c?: number | null; distance_m?: number | null }) => dispatch({ type: "setOptics", id: r.id, ...patch });
  return (
    <div className="optics">
      <div className="optics-title">Optics · {roiLabel(r)}</div>
      <div className="optics-grid">
        <label htmlFor={`eps-${r.id}`}>emissivity</label>
        <NumberField id={`eps-${r.id}`} min={0.01} max={1} step={0.01} value={r.emissivity ?? null} placeholder="camera" aria-label={`emissivity of ${roiLabel(r)}`} onChange={(n) => set({ emissivity: n })} />
        <span className="optics-unit" title="Corrects this region's reading live (largest effect). 0.01–1.">ε</span>

        <label htmlFor={`refl-${r.id}`}>reflected</label>
        <NumberField id={`refl-${r.id}`} step={0.5} value={r.reflected_c ?? null} placeholder="camera" aria-label={`reflected temperature of ${roiLabel(r)} in °C`} onChange={(n) => set({ reflected_c: n })} />
        <span className="optics-unit" title="Reflected apparent temperature of the surroundings. Corrects the reading live.">°C</span>

        <label htmlFor={`dist-${r.id}`}>distance</label>
        <NumberField id={`dist-${r.id}`} min={0.01} step={0.1} value={r.distance_m ?? null} placeholder="camera" aria-label={`object distance of ${roiLabel(r)} in metres`} onChange={(n) => set({ distance_m: n })} />
        <span className="optics-unit" title="Recorded with the ROI for your own atmospheric correction. Under ~2 m it changes the reading by under a few tenths of a degree.">m</span>
      </div>
      <div className="optics-foot">
        Blank = use the camera's global setting.{" "}
        {(r.emissivity !== undefined || r.reflected_c !== undefined || r.distance_m !== undefined) && (
          <button type="button" className="secondary" onClick={() => set({ emissivity: null, reflected_c: null, distance_m: null })} title="Clear this ROI's emissivity, reflected temperature and distance so it uses the camera's settings">Reset to camera</button>
        )}
      </div>
    </div>
  );
}

/** One row per ROI: color swatch (click to change), editable name, current values, remove. */
export function RoiRows({ rois, stats, selected, selectedIds, dispatch, extremes, onExtremes, units = "C", conv = null, smartFeed, smartOverlays, smartPlayback, smartView = {}, onSmartView, scope = "live" }: Props) {
  const isSel = (id: number) => (selectedIds ? selectedIds.includes(id) : selected === id);
  const [editing, setEditing] = useState<number | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const [optics, setOptics] = useState<number | null>(null);
  const help = (
    <Disclosure label="How to draw and edit ROIs">
      <ul className="help">
        <li>◎ Spot: click a pixel.</li>
        <li>▭ Rectangle: drag corner to corner.</li>
        <li>◯ Circle: drag from the centre outwards. ⬭ Ellipse: drag its bounding box corner to corner.</li>
        <li>╱ Line: drag from one end to the other; the pixels along it are measured.</li>
        <li>⬠ Polygon: click each vertex; double-click places the last one and closes the shape (Enter closes, Esc cancels, Backspace undoes a vertex). ⌇ Spline: the same, but open. ✎ Freehand: hold the mouse and draw; releasing closes the shape.</li>
        <li>↖ Select: click an ROI, then drag to move it; Delete removes it. Shift-click to select several and drag them together. ROIs stacked on top of each other: press 1–9 to select that row's ROI (or Alt/Option-click to step down through the stack), then drag anywhere inside it, even where others cover it. When a polygon, spline or line is selected, drag its square handles to edit individual vertices. Cmd/Ctrl+Z undoes an ROI change; Cmd/Ctrl+Y or Cmd/Ctrl+Shift+Z redoes it.</li>
        <li>Smart tool: draw a loose outline around the sample (like freehand). The operator finds the sample's thermal edge inside it every frame and draws it solid, with the ring bands dashed; ⚙ sets the rings, edge rule, sensitivity and ring emissivity. Its size is measured from the thermal edge.</li>
        <li>Click the color square to recolor, set a per-ROI emissivity and reflected temperature (values are re-corrected from the camera's setting); double-click the name to rename; ◉ hides an ROI on the image and plot without removing it.</li>
      </ul>
    </Disclosure>
  );
  if (rois.length === 0) return <><div className="hint">No ROIs yet.</div>{help}</>;
  return (
    <>
      <div className="roi-rows">
        {rois.map((r, i) => (
          [
            <span key={`l${r.id}`} className={`lbl ${isSel(r.id) ? "sel" : ""}`} title={where(r)}>
              <button type="button" className="sw" style={{ background: roiColor(r, i), border: "none" }} aria-label={`color of ${roiLabel(r)}`}
                onClick={() => setPicking(picking === r.id ? null : r.id)} />
              {editing === r.id ? (
                <input autoFocus type="text" defaultValue={r.name ?? ""} placeholder={roiId(r)} aria-label="ROI name" maxLength={40}
                  onBlur={(e) => { dispatch({ type: "rename", id: r.id, name: e.target.value }); setEditing(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditing(null); }} />
              ) : (
                <button type="button" className="lbl" style={{ border: "none", padding: 0 }} aria-pressed={isSel(r.id)}
                  onClick={(e) => dispatch(e.shiftKey ? { type: "toggleSelect", id: r.id } : { type: "select", id: selected === r.id && selectedIds?.length === 1 ? null : r.id })} onDoubleClick={() => setEditing(r.id)} title={`${where(r)} · double-click to rename`}>
                  {i < 9 ? <small className="muted" title={`press ${i + 1} to select`}>{i + 1}·</small> : null}{roiLabel(r)}{r.name ? <small className="muted"> {roiId(r)}</small> : null}{r.emissivity !== undefined ? <small className="muted" title={`per-ROI emissivity ${r.emissivity}`}> ε{r.emissivity}</small> : null}
                </button>
              )}
            </span>,
            r.kind === "smart" ? <SmartValue key={`v${r.id}`} id={r.id} feed={smartFeed} overlays={smartOverlays} played={smartPlayback?.get(r.id)} units={units} conv={conv} /> : <Values key={`v${r.id}`} s={stats.get(r.id)} units={units} conv={conv} />,
            <span key={`x${r.id}`} style={{ display: "flex", gap: 4 }}>
              <button className="secondary" type="button" onClick={() => dispatch({ type: "toggleHidden", id: r.id })} aria-pressed={!!r.hidden} aria-label={`${r.hidden ? "Show" : "Hide"} ${roiLabel(r)}`} title={r.hidden ? "Hidden on the image (still measured and recorded) · click to show" : "Hide on the image (still measured and recorded)"} style={{ opacity: r.hidden ? 0.5 : 1 }}>{r.hidden ? "◌" : "◉"}</button>
              {r.kind === "smart" ? <button className="secondary" type="button" onClick={() => setOptics(optics === r.id ? null : r.id)} aria-pressed={optics === r.id} aria-label={`Smart ROI settings for ${roiLabel(r)}`} title="Smart ROI settings: ring offsets, edge rule, sensitivity, ring emissivity">⚙</button> :
              <button className="secondary" type="button" onClick={() => setOptics(optics === r.id ? null : r.id)} aria-pressed={optics === r.id} aria-label={`Optics for ${roiLabel(r)}`} title="Per-ROI emissivity, reflected temperature and distance (for accuracy on this region)" style={{ fontWeight: (r.emissivity !== undefined || r.reflected_c !== undefined || r.distance_m !== undefined) ? 700 : 400, color: (r.emissivity !== undefined || r.reflected_c !== undefined || r.distance_m !== undefined) ? "var(--accent)" : undefined }}>ε</button>}
              <button className="secondary" type="button" onClick={() => { dispatch({ type: "commit" }); dispatch({ type: "remove", id: r.id }); dispatch({ type: "commit" }); }} aria-label={`Remove ${roiLabel(r)}`} title="Remove">×</button>
            </span>,
            r.kind === "smart" ? <SmartLines key={`s${r.id}`} r={r} scope={scope} feed={smartFeed} overlays={smartOverlays} played={smartPlayback?.get(r.id)} prefs={smartPrefs(smartView, scope, r.id)} onView={onSmartView} /> : <StatsLine key={`s${r.id}`} r={r} s={stats.get(r.id)} units={units} conv={conv} />,
            picking === r.id ? <div key={`c${r.id}`} style={{ gridColumn: "1 / -1" }}><ColorPicker r={r} i={i} dispatch={dispatch} onDone={() => setPicking(null)} /></div> : null,
            optics === r.id ? <div key={`o${r.id}`} style={{ gridColumn: "1 / -1" }}>{r.kind === "smart" ? <SmartEditor r={r} dispatch={dispatch} /> : <OpticsEditor r={r} dispatch={dispatch} />}</div> : null,
          ]
        ))}
      </div>
      <div className="row">
        <button className="secondary" type="button" onClick={() => dispatch({ type: "setHiddenAll", hidden: !rois.every((r) => r.hidden) })} title="Hide or show every ROI on the image; measurements, recording and exports are unaffected">{rois.every((r) => r.hidden) ? "show all" : "hide all"}</button>
        <button className="secondary" type="button" onClick={() => dispatch({ type: "clear" })}>clear all</button>
        <button className="secondary" type="button" title="Save this ROI set as a JSON file (load it on any machine or recording)" onClick={() => {
          const blob = new Blob([JSON.stringify({ format: "fri-rois-1", rois }, null, 2)], { type: "application/json" });
          const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "rois.json"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        }}>save…</button>
        <label className="secondary" style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", padding: "5px 10px", border: "1px solid var(--line-control)", borderRadius: "var(--radius)", fontFamily: "var(--font-mono)", fontSize: 12 }} title="Load an ROI set from a JSON file (replaces the current set)">
          load…<input type="file" accept="application/json,.json" style={{ display: "none" }} onChange={(e) => {
            const f = e.target.files?.[0]; if (!f) return;
            void f.text().then((txt) => {
              const parsed = loadRois({ getItem: () => JSON.stringify({ rois: (JSON.parse(txt) as { rois?: unknown }).rois ?? JSON.parse(txt), nextId: 1 }), setItem: () => undefined } as unknown as Storage);
              dispatch({ type: "replace", rois: parsed.rois });
            }).catch(() => undefined);
            e.target.value = "";
          }} />
        </label>
        {onExtremes && <button className="secondary" type="button" aria-pressed={!!extremes} onClick={() => onExtremes(!extremes)} title="Mark the hottest (▲) and coldest (▽) pixel inside every area ROI" style={{ marginLeft: "auto", opacity: extremes ? 1 : 0.6 }}>▲▽ hot/cold</button>}
      </div>
      {help}
    </>
  );
}
