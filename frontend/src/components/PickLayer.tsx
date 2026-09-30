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
  /** Display flip applied to the image underneath; picks are stored in unflipped image coordinates. */
  flipH?: boolean;
  flipV?: boolean;
}

/** Transparent click layer over an image: collects normalised points and draws numbered markers. */
export function PickLayer({ points, pending, color, onPick, label, flipH = false, flipV = false }: Props) {
  // Screen <-> image is the same mapping both ways (a flip is its own inverse).
  const toImage = (p: Pt): Pt => [flipH ? 1 - p[0] : p[0], flipV ? 1 - p[1] : p[1]];
  function onClick(e: RMouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    onPick(toImage([(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]));
  }
  const at = (p: Pt) => { const q = toImage(p); return { left: `${q[0] * 100}%`, top: `${q[1] * 100}%` }; };
  return (
    <div className="pick-layer" onClick={onClick} role="button" aria-label={`pick a point on the ${label} image`} style={{ cursor: "crosshair" }}>
      {points.map((p, i) => (
        <span key={i} className="pick-mark" style={{ ...at(p), borderColor: color, color }}>{i + 1}</span>
      ))}
      {pending && <span className="pick-mark pending" style={{ ...at(pending), borderColor: color, color }}>{points.length + 1}</span>}
      <span className="pick-hint">{label}: click feature {points.length + 1}</span>
    </div>
  );
}
