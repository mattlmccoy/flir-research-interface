import type { ReactNode } from "react";
import { TOOLS, type Tool } from "../../lib/layout.ts";

/** Presentation for each tool id (ids come from TOOLS in lib/layout.ts). */
const TOOL_META: Record<Tool, { glyph: string; title: string; enabled: boolean }> = {
  select: { glyph: "↖", title: "Select: click an ROI to select it (Delete removes it)", enabled: true },
  spot: { glyph: "◎", title: "Spot: click to place a single-pixel measurement", enabled: true },
  rect: { glyph: "▭", title: "Rectangle: drag corner to corner", enabled: true },
  circle: { glyph: "◯", title: "Circle: drag from the centre outwards", enabled: true },
  line: { glyph: "╱", title: "Line: drag from one end to the other (pixels along the segment)", enabled: true },
  polygon: { glyph: "⬠", title: "Polygon: click each vertex; double-click places the last one and closes the shape (Enter closes, Esc cancels)", enabled: true },
};

interface Props {
  tool: Tool;
  onTool: (t: Tool) => void;
  onCollapseAll: () => void;
  /** Rendered before the tools (e.g. a back button on the playback page). */
  leading?: ReactNode;
  /** Tools that make no sense in this context (e.g. camera controls during playback). */
  disabledTools?: readonly Tool[];
}

/**
 * Left icon strip (spec §3). Disabled tools stay visible so the layout never shifts between
 * releases; they use aria-disabled (not the disabled attribute) so their tooltip still shows.
 */
export function ToolStrip({ tool, onTool, onCollapseAll, leading, disabledTools = [] }: Props) {
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
            title={m.title}
            aria-label={m.title}
            aria-disabled={!enabled}
            aria-pressed={tool === id}
            onClick={() => { if (enabled) onTool(id); }}
          >
            {m.glyph}
          </button>
        );
      })}
      <span className="spacer" />
      <button aria-label="Hide panels (image only)" title="Hide panels (image only)" onClick={onCollapseAll}>⛶</button>
    </nav>
  );
}
