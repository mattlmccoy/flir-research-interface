import type { ReactNode } from "react";
import type { LayoutState } from "../../lib/layout.ts";

interface Props {
  layout: LayoutState;
  /** true for setup/experiments pages: center spans full height, no dock, strip hidden */
  page?: boolean;
  topbar: ReactNode;
  strip?: ReactNode;
  center: ReactNode;
  dock?: ReactNode;
  rail?: ReactNode;
  statusbar: ReactNode;
}

/** The Studio grid (spec §3). Panels collapse via layout flags; grid areas are fixed. */
export function StudioFrame({ layout, page = false, topbar, strip, center, dock, rail, statusbar }: Props) {
  const showStrip = !page && layout.strip && !!strip;
  const showRail = layout.rail && !!rail;
  const showDock = !page && layout.dock && !!dock;
  const cls = ["studio", page ? "page" : "", showStrip ? "" : "no-strip", showRail ? "" : "no-rail", showDock ? "" : "no-dock"]
    .filter(Boolean).join(" ");
  return (
    <div className={cls}>
      <div className="topbar">{topbar}</div>
      {showStrip && strip}
      <div className="center">
        {center}
        {showDock && dock}
      </div>
      {showRail && rail}
      {statusbar}
    </div>
  );
}
