import { roiLabel, type Roi, type RoiStats } from "../lib/roi.ts";
import { traceColor } from "../lib/overlay.ts";

interface Props {
  rois: Roi[];
  stats: Map<number, RoiStats>;
  selected: number | null;
  onSelect: (id: number | null) => void;
  onRemove: (id: number) => void;
  onClear: () => void;
}

function Values({ r, s }: { r: Roi; s: RoiStats | undefined }) {
  if (!s) return <span className="vals">…</span>;
  if (s.n === 0 || s.mean === null) return <span className="vals">n/a</span>;
  if (r.kind === "spot") return <span className="vals">{s.mean.toFixed(2)} °C</span>;
  return (
    <span className="vals">
      {s.mean.toFixed(2)} °C
      <small>min {(s.min as number).toFixed(2)} · max {(s.max as number).toFixed(2)}</small>
    </span>
  );
}

function where(r: Roi): string {
  return r.kind === "spot" ? `x ${r.x} y ${r.y}` : `x ${r.x0}…${r.x1 - 1} y ${r.y0}…${r.y1 - 1} (${r.x1 - r.x0}×${r.y1 - r.y0} px)`;
}

/** One row per ROI: colour swatch + label, current values (mean; min/max for rectangles), remove. */
export function RoiRows({ rois, stats, selected, onSelect, onRemove, onClear }: Props) {
  if (rois.length === 0) return <div className="hint">No ROIs. Use ◎ (spot) or ▭ (rectangle) in the tool strip, then click or drag on the image.</div>;
  return (
    <>
      <div className="roi-rows">
        {rois.map((r, i) => (
          [
            <button key={`l${r.id}`} className={`lbl ${selected === r.id ? "sel" : ""}`} type="button"
              onClick={() => onSelect(selected === r.id ? null : r.id)} aria-pressed={selected === r.id} title={where(r)}>
              <span className="sw" style={{ background: traceColor(i) }} />{roiLabel(r)}
            </button>,
            <Values key={`v${r.id}`} r={r} s={stats.get(r.id)} />,
            <button key={`x${r.id}`} className="secondary" type="button" onClick={() => onRemove(r.id)} aria-label={`Remove ${roiLabel(r)}`} title="Remove">×</button>,
          ]
        ))}
      </div>
      <div className="row"><button className="secondary" type="button" onClick={onClear}>clear all</button><span className="hint">Delete removes the selected ROI.</span></div>
    </>
  );
}
