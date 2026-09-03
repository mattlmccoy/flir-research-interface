import { NumberField } from "./NumberField.tsx";
import { convertTemp, fmtTemp, type Conversion, type Units } from "../lib/units.ts";
import { useState } from "react";
import { roiId, roiLabel, type Roi, type RoiAction, type RoiStats, loadRois } from "../lib/roi.ts";
import { COLOR_PRESETS, roiColor } from "../lib/overlay.ts";
import { Disclosure } from "./Disclosure.tsx";

interface Props {
  units?: Units; conv?: Conversion | null;
  /** Hot/cold marker toggle (undefined hides the button). */
  extremes?: boolean; onExtremes?: (on: boolean) => void;
  rois: Roi[];
  stats: Map<number, RoiStats>;
  selected: number | null; selectedIds?: number[];
  dispatch: (a: RoiAction) => void;
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
    case "polyline": return `bendable line with ${r.points.length} vertices`;
  }
}

function ColorPicker({ r, i, dispatch, onDone }: { r: Roi; i: number; dispatch: (a: RoiAction) => void; onDone: () => void }) {
  const current = roiColor(r, i);
  return (
    <div className="swatches" role="group" aria-label={`colour of ${roiLabel(r)}`}>
      {COLOR_PRESETS.map((c) => (
        <button key={c} type="button" className={current.toLowerCase() === c ? "on" : ""} style={{ background: c }} title={c}
          onClick={() => { dispatch({ type: "recolor", id: r.id, color: c }); onDone(); }} />
      ))}
      <input type="color" aria-label="custom colour" value={r.color ?? "#ffffff"} title="any colour"
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
      <div className="optics-foot">Blank = use the camera's global setting.</div>
    </div>
  );
}

/** One row per ROI: colour swatch (click to change), editable name, current values, remove. */
export function RoiRows({ rois, stats, selected, selectedIds, dispatch, extremes, onExtremes, units = "C", conv = null }: Props) {
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
        <li>⬠ Polygon: click each vertex; double-click places the last one and closes the shape (Enter closes, Esc cancels, Backspace undoes a vertex). ⌇ Bendable line: the same, but open. ✎ Freehand: hold the mouse and draw; releasing closes the shape.</li>
        <li>↖ Select: click an ROI, then drag to move it; Delete removes it. Shift-click to select several and drag them together. When a polygon, bendable line or line is selected, drag its square handles to edit individual vertices.</li>
        <li>Click the colour square to recolour, set a per-ROI emissivity and reflected temperature (values are re-corrected from the camera's setting); double-click the name to rename; ◉ hides an ROI on the image and plot without removing it.</li>
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
              <button type="button" className="sw" style={{ background: roiColor(r, i), border: "none" }} aria-label={`colour of ${roiLabel(r)}`}
                onClick={() => setPicking(picking === r.id ? null : r.id)} />
              {editing === r.id ? (
                <input autoFocus type="text" defaultValue={r.name ?? ""} placeholder={roiId(r)} aria-label="ROI name" maxLength={40}
                  onBlur={(e) => { dispatch({ type: "rename", id: r.id, name: e.target.value }); setEditing(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditing(null); }} />
              ) : (
                <button type="button" className="lbl" style={{ border: "none", padding: 0 }} aria-pressed={isSel(r.id)}
                  onClick={(e) => dispatch(e.shiftKey ? { type: "toggleSelect", id: r.id } : { type: "select", id: selected === r.id && selectedIds?.length === 1 ? null : r.id })} onDoubleClick={() => setEditing(r.id)} title={`${where(r)} · double-click to rename`}>
                  {roiLabel(r)}{r.name ? <small className="muted"> {roiId(r)}</small> : null}{r.emissivity !== undefined ? <small className="muted" title={`per-ROI emissivity ${r.emissivity}`}> ε{r.emissivity}</small> : null}
                </button>
              )}
            </span>,
            <Values key={`v${r.id}`} s={stats.get(r.id)} units={units} conv={conv} />,
            <span key={`x${r.id}`} style={{ display: "flex", gap: 4 }}>
              <button className="secondary" type="button" onClick={() => setOptics(optics === r.id ? null : r.id)} aria-pressed={optics === r.id} aria-label={`Optics for ${roiLabel(r)}`} title="Per-ROI emissivity, reflected temperature and distance (for accuracy on this region)" style={{ fontWeight: (r.emissivity !== undefined || r.reflected_c !== undefined || r.distance_m !== undefined) ? 700 : 400, color: (r.emissivity !== undefined || r.reflected_c !== undefined || r.distance_m !== undefined) ? "var(--accent)" : undefined }}>ε</button>
              <button className="secondary" type="button" onClick={() => dispatch({ type: "toggleHidden", id: r.id })} aria-pressed={!!r.hidden} aria-label={`${r.hidden ? "Show" : "Hide"} ${roiLabel(r)}`} title={r.hidden ? "Hidden on the image (still measured and recorded) · click to show" : "Hide on the image (still measured and recorded)"} style={{ opacity: r.hidden ? 0.5 : 1 }}>{r.hidden ? "◌" : "◉"}</button>
              <button className="secondary" type="button" onClick={() => dispatch({ type: "remove", id: r.id })} aria-label={`Remove ${roiLabel(r)}`} title="Remove">×</button>
            </span>,
            <StatsLine key={`s${r.id}`} r={r} s={stats.get(r.id)} units={units} conv={conv} />,
            picking === r.id ? <div key={`c${r.id}`} style={{ gridColumn: "1 / -1" }}><ColorPicker r={r} i={i} dispatch={dispatch} onDone={() => setPicking(null)} /></div> : null,
            optics === r.id ? <div key={`o${r.id}`} style={{ gridColumn: "1 / -1" }}><OpticsEditor r={r} dispatch={dispatch} /></div> : null,
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
