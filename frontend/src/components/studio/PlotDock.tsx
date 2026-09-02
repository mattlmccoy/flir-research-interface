import type { ReactNode } from "react";

interface Props { title?: string; onCollapse: () => void; children?: ReactNode; }

export function PlotDock({ title = "temperature vs time", onCollapse, children }: Props) {
  return (
    <div className="dock">
      <div className="dock-head">
        <span>{title}</span>
        <button className="secondary" aria-label="Collapse dock" title="Collapse dock" onClick={onCollapse}>▾</button>
      </div>
      <div className="dock-body">{children ?? <span>plots arrive with ROIs (Milestone 6)</span>}</div>
    </div>
  );
}
