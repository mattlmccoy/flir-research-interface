import type { ReactNode } from "react";
import { studioClasses, type LayoutState } from "../../lib/layout.ts";

interface Props {
  layout: LayoutState;
  /** true for setup/experiments pages: center spans full height, no dock, strip hidden */
  page?: boolean;
  topbar: ReactNode;
  /**
   * Slot contract: each of `strip`, `rail`, `statusbar` must render exactly one element bearing
   * the grid's own class (`strip`, `rail`, `statusbar` respectively — see ToolStrip, Rail,
   * StatusBar). The Studio grid areas are keyed to those classes; a fragment, `null`, or more
   * than one top-level element in a slot would create implicit/extra grid rows.
   */
  strip?: ReactNode;
  center: ReactNode;
  dock?: ReactNode;
  rail?: ReactNode;
  statusbar: ReactNode;
}

/** The Studio grid (spec §3). Panels collapse via layout flags; grid areas are fixed. */
export function StudioFrame({ layout, page = false, topbar, strip, center, dock, rail, statusbar }: Props) {
  const { className, showStrip, showRail, showDock } = studioClasses(layout, {
    page,
    hasStrip: !!strip,
    hasRail: !!rail,
    hasDock: !!dock,
  });
  return (
    <div className={className}>
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
