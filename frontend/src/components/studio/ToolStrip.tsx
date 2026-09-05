import type { ReactNode } from "react";
import { TOOLS, type Tool } from "../../lib/layout.ts";
import { nextZoom, zoomLabel, type Zoom } from "../../lib/zoom.ts";

/** Presentation for each tool id (ids come from TOOLS in lib/layout.ts). */
const TOOL_META: Record<Tool, { glyph: string; title: string; enabled: boolean }> = {
  select: { glyph: "↖", title: "Select: click an ROI to select it (Delete removes it)", enabled: true },
  spot: { glyph: "◎", title: "Spot: click to place a single-pixel measurement", enabled: true },
  rect: { glyph: "▭", title: "Rectangle: drag corner to corner", enabled: true },
  circle: { glyph: "◯", title: "Circle: drag from the centre outwards", enabled: true },
  ellipse: { glyph: "⬭", title: "Ellipse: drag the bounding box corner to corner", enabled: true },
  polyline: { glyph: "⌇", title: "Spline: click each vertex; double-click or Enter ends it", enabled: true },
  freehand: { glyph: "✎", title: "Freehand: hold and draw; releasing closes the shape", enabled: true },
  line: { glyph: "╱", title: "Line: drag from one end to the other (pixels along the segment)", enabled: true },
  polygon: { glyph: "⬠", title: "Polygon: click each vertex; double-click places the last one and closes the shape (Enter closes, Esc cancels)", enabled: true },
};

interface Props {
  tool: Tool;
  onTool: (t: Tool) => void;
  onCollapseAll: () => void;
  /** Rendered before the tools (e.g. a back button on the playback page). */
  leading?: ReactNode;
  /** Shortcut buttons rendered under the tools, below a divider (e.g. media export). */
  extras?: ReactNode;
  /** Panels are hidden: the ⛶ button restores them instead. */
  collapsed?: boolean;
  /** Tools that make no sense in this context (e.g. camera controls during playback). */
  disabledTools?: readonly Tool[];
  zoom?: Zoom;
  onZoom?: (z: Zoom) => void;
}

/**
 * Left icon strip (spec §3). Disabled tools stay visible so the layout never shifts between
 * releases; they use aria-disabled (not the disabled attribute) so their tooltip still shows.
 */
export function ToolStrip({ tool, onTool, onCollapseAll, leading, extras, disabledTools = [], zoom = "fit", onZoom, collapsed = false }: Props) {
  return (
    <nav className="strip" aria-label="tools">
      {leading}
      {TOOLS.map((id) => {
        const m = TOOL_META[id];
        const enabled = m.enabled && !disabledTools.includes(id);
        return (
          <button
            key={id}
            className={tool === id ? "active" : ""}
            data-tip={m.title}
            aria-label={m.title}
            aria-disabled={!enabled}
            aria-pressed={tool === id}
            onClick={() => { if (enabled) onTool(id); }}
          >
            {m.glyph}
          </button>
        );
      })}
      {extras && <><span className="divider" role="separator" />{extras}</>}
      <span className="spacer" />
      {onZoom && (
        <button className={`zoom ${zoom === "fit" ? "active" : ""}`} aria-label={`Image zoom: ${zoomLabel(zoom)} (click to cycle fit, 1:1, 2×)`} data-tip={`Zoom ${zoomLabel(zoom)} · click: ${zoomLabel(nextZoom(zoom))}`} onClick={() => onZoom(nextZoom(zoom))}>
          {zoom === "fit" ? "⤢" : zoomLabel(zoom)}
        </button>
      )}
      <button className={collapsed ? "active" : ""} aria-pressed={collapsed} aria-label={collapsed ? "Restore panels" : "Hide panels (image only)"} data-tip={collapsed ? "Restore panels" : "Hide panels (image only)"} onClick={onCollapseAll}>⛶</button>
    </nav>
  );
}
