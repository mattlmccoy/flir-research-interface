import type { ReactNode } from "react";

interface Props { title?: string; onCollapse: () => void; controls?: ReactNode; children?: ReactNode; }

/** Bottom dock housing the temperature-vs-time plot; `controls` sit in the header (window, export). */
export function PlotDock({ title = "temperature vs time", onCollapse, controls, children }: Props) {
  return (
    <div className="dock">
      <div className="dock-head">
        <span>{title}</span>
        <span className="ctl">
          {controls}
          <button className="secondary" aria-label="Collapse dock" title="Collapse dock" onClick={onCollapse}>▾</button>
        </span>
      </div>
      <div className={`dock-body ${children ? "plot-body" : ""}`}>{children ?? <span>no plot</span>}</div>
    </div>
  );
}
