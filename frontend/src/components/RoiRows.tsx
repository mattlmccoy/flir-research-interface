import { useState } from "react";
import { roiId, roiLabel, type Roi, type RoiAction, type RoiStats } from "../lib/roi.ts";
import { COLOR_PRESETS, roiColor } from "../lib/overlay.ts";
import { Disclosure } from "./Disclosure.tsx";

interface Props {
  /** Hot/cold marker toggle (undefined hides the button). */
  extremes?: boolean; onExtremes?: (on: boolean) => void;
  rois: Roi[];
  stats: Map<number, RoiStats>;
  selected: number | null;
  dispatch: (a: RoiAction) => void;
}

function Values({ r, s }: { r: Roi; s: RoiStats | undefined }) {
  if (!s) return <span className="vals">…</span>;
  if (s.n === 0 || s.mean === null) return <span className="vals">n/a</span>;
  if (r.kind === "spot") return <span className="vals">{s.mean.toFixed(2)} °C</span>;
  return (
    <span className="vals">
      {s.mean.toFixed(2)} °C
      <small>min {(s.min as number).toFixed(2)} · max {(s.max as number).toFixed(2)}{s.std !== undefined ? ` · σ ${s.std.toFixed(2)}` : ""} · {s.n} px</small>
    </span>
  );
}

function where(r: Roi): string {
  switch (r.kind) {
    case "spot": return `spot x ${r.x} y ${r.y}`;
    case "rect": return `rect x ${r.x0}…${r.x1 - 1} y ${r.y0}…${r.y1 - 1} (${r.x1 - r.x0}×${r.y1 - r.y0} px)`;
    case "circle": return `circle centre (${r.cx}, ${r.cy}) r ${r.r.toFixed(1)} px`;
    case "line": return `line (${r.x0}, ${r.y0}) → (${r.x1}, ${r.y1})`;
    case "polygon": return `polygon with ${r.points.length} vertices`;
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
      <span className="hint" style={{ flexBasis: "100%", display: "flex", gap: 6, alignItems: "center", marginTop: 4 }} title="Per-ROI optics: this ROI's values are re-corrected from the camera's global emissivity / reflected temperature using the camera's own R, B, F constants (FLIR signal model, atmosphere ≈ 1). Leave blank to use the camera's setting.">
        ε <input type="number" min={0.01} max={1} step={0.01} value={r.emissivity ?? ""} placeholder="camera" style={{ width: 64 }} aria-label={`emissivity of ${roiLabel(r)}`}
          onChange={(e) => dispatch({ type: "setOptics", id: r.id, emissivity: e.target.value === "" ? null : Number(e.target.value) })} />
        T<sub>refl</sub> <input type="number" step={0.5} value={r.reflected_c ?? ""} placeholder="camera" style={{ width: 64 }} aria-label={`reflected temperature of ${roiLabel(r)} in °C`}
          onChange={(e) => dispatch({ type: "setOptics", id: r.id, reflected_c: e.target.value === "" ? null : Number(e.target.value) })} /> °C
      </span>
    </div>
  );
}

/** One row per ROI: colour swatch (click to change), editable name, current values, remove. */
export function RoiRows({ rois, stats, selected, dispatch, extremes, onExtremes }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const help = (
    <Disclosure label="How to draw and edit ROIs">
      <ul className="help">
        <li>◎ Spot: click a pixel.</li>
        <li>▭ Rectangle: drag corner to corner.</li>
        <li>◯ Circle: drag from the centre outwards.</li>
        <li>╱ Line: drag from one end to the other; the pixels along it are measured.</li>
        <li>⬠ Polygon: click each vertex; double-click places the last one and closes the shape (Enter closes, Esc cancels, Backspace undoes a vertex).</li>
        <li>↖ Select: click an ROI, then drag to move it; Delete removes it.</li>
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
            <span key={`l${r.id}`} className={`lbl ${selected === r.id ? "sel" : ""}`} title={where(r)}>
              <button type="button" className="sw" style={{ background: roiColor(r, i), border: "none" }} aria-label={`colour of ${roiLabel(r)}`}
                onClick={() => setPicking(picking === r.id ? null : r.id)} />
              {editing === r.id ? (
                <input autoFocus type="text" defaultValue={r.name ?? ""} placeholder={roiId(r)} aria-label="ROI name" maxLength={40}
                  onBlur={(e) => { dispatch({ type: "rename", id: r.id, name: e.target.value }); setEditing(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEditing(null); }} />
              ) : (
                <button type="button" className="lbl" style={{ border: "none", padding: 0 }} aria-pressed={selected === r.id}
                  onClick={() => dispatch({ type: "select", id: selected === r.id ? null : r.id })} onDoubleClick={() => setEditing(r.id)} title={`${where(r)} · double-click to rename`}>
                  {roiLabel(r)}{r.name ? <small className="muted"> {roiId(r)}</small> : null}{r.emissivity !== undefined ? <small className="muted" title={`per-ROI emissivity ${r.emissivity}`}> ε{r.emissivity}</small> : null}
                </button>
              )}
            </span>,
            <Values key={`v${r.id}`} r={r} s={stats.get(r.id)} />,
            <span key={`x${r.id}`} style={{ display: "flex", gap: 4 }}>
              <button className="secondary" type="button" onClick={() => dispatch({ type: "toggleHidden", id: r.id })} aria-pressed={!!r.hidden} aria-label={`${r.hidden ? "Show" : "Hide"} ${roiLabel(r)}`} title={r.hidden ? "Hidden on the image (still measured and recorded) · click to show" : "Hide on the image (still measured and recorded)"} style={{ opacity: r.hidden ? 0.5 : 1 }}>{r.hidden ? "◌" : "◉"}</button>
              <button className="secondary" type="button" onClick={() => dispatch({ type: "remove", id: r.id })} aria-label={`Remove ${roiLabel(r)}`} title="Remove">×</button>
            </span>,
            picking === r.id ? <div key={`c${r.id}`} style={{ gridColumn: "1 / -1" }}><ColorPicker r={r} i={i} dispatch={dispatch} onDone={() => setPicking(null)} /></div> : null,
          ]
        ))}
      </div>
      <div className="row">
        <button className="secondary" type="button" onClick={() => dispatch({ type: "setHiddenAll", hidden: !rois.every((r) => r.hidden) })} title="Hide or show every ROI on the image; measurements, recording and exports are unaffected">{rois.every((r) => r.hidden) ? "show all" : "hide all"}</button>
        <button className="secondary" type="button" onClick={() => dispatch({ type: "clear" })}>clear all</button>
        {onExtremes && <button className="secondary" type="button" aria-pressed={!!extremes} onClick={() => onExtremes(!extremes)} title="Mark the hottest (▲) and coldest (▽) pixel inside every area ROI" style={{ marginLeft: "auto", opacity: extremes ? 1 : 0.6 }}>▲▽ hot/cold</button>}
      </div>
      {help}
    </>
  );
}
