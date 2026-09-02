import type { MouseEvent as RMouseEvent } from "react";
import type { Pt } from "../lib/homography.ts";

interface Props {
  /** Normalised (0..1) points already picked on this image, in order. */
  points: Pt[];
  /** A half-finished pick on this image (drawn hollow). */
  pending?: Pt | null;
  color: string;
  onPick: (p: Pt) => void;
  label: string;
}

/** Transparent click layer over an image: collects normalised points and draws numbered markers. */
export function PickLayer({ points, pending, color, onPick, label }: Props) {
  function onClick(e: RMouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    onPick([(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]);
  }
  return (
    <div className="pick-layer" onClick={onClick} role="button" aria-label={`pick a point on the ${label} image`} style={{ cursor: "crosshair" }}>
      {points.map((p, i) => (
        <span key={i} className="pick-mark" style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%`, borderColor: color, color }}>{i + 1}</span>
      ))}
      {pending && <span className="pick-mark pending" style={{ left: `${pending[0] * 100}%`, top: `${pending[1] * 100}%`, borderColor: color, color }}>{points.length + 1}</span>}
      <span className="pick-hint">{label}: click feature {points.length + 1}</span>
    </div>
  );
}
