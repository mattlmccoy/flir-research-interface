import { roiLabel, type Roi } from "../lib/roi.ts";

interface Props { rois: Roi[]; delta: { a: number; b: number } | null; onChange: (d: { a: number; b: number } | null) => void; }

/** "Δ A − B" selector for the time plot: an extra trace of the difference between two ROIs. */
export function DeltaPicker({ rois, delta, onChange }: Props) {
  if (rois.length < 2) return null;
  const a = delta?.a ?? rois[0].id, b = delta?.b ?? rois[1].id;
  const opt = (r: Roi) => <option key={r.id} value={r.id}>{roiLabel(r)}</option>;
  return (
    <span className="row" style={{ gap: 4, alignItems: "center", flexWrap: "nowrap" }} title="Plot the difference between two ROIs (mean, or value for spots) as an extra trace">
      <label className="hint"><input type="checkbox" checked={!!delta} onChange={(e) => onChange(e.target.checked ? { a, b } : null)} /> Δ</label>
      <select value={a} disabled={!delta} aria-label="delta A" style={{ maxWidth: 150 }} onChange={(e) => onChange({ a: Number(e.target.value), b })}>{rois.map(opt)}</select>
      <span className="hint">−</span>
      <select value={b} disabled={!delta} aria-label="delta B" style={{ maxWidth: 150 }} onChange={(e) => onChange({ a, b: Number(e.target.value) })}>{rois.map(opt)}</select>
    </span>
  );
}
