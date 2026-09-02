import { TOOLS, type Tool } from "../../lib/layout.ts";

/** Presentation for each tool id (ids come from TOOLS in lib/layout.ts). */
const TOOL_META: Record<Tool, { glyph: string; title: string; enabled: boolean }> = {
  select: { glyph: "↖", title: "Select / hover readout", enabled: true },
  spot: { glyph: "◎", title: "Spot (Milestone 6)", enabled: false },
  rect: { glyph: "▭", title: "Rectangle ROI (Milestone 6)", enabled: false },
  line: { glyph: "╱", title: "Line profile (later)", enabled: false },
  display: { glyph: "▤", title: "Palette & range", enabled: true },
  camera: { glyph: "⚙", title: "Camera controls (Milestone 6)", enabled: false },
  nuc: { glyph: "N", title: "NUC (Milestone 6)", enabled: false },
};

interface Props { tool: Tool; onTool: (t: Tool) => void; onCollapseAll: () => void; }

/**
 * Left icon strip (spec §3). Disabled tools stay visible so the layout never shifts between
 * releases; they use aria-disabled (not the disabled attribute) so their tooltip still shows.
 */
export function ToolStrip({ tool, onTool, onCollapseAll }: Props) {
  return (
    <nav className="strip" aria-label="tools">
      {TOOLS.map((id) => {
        const m = TOOL_META[id];
        return (
          <button
            key={id}
            className={tool === id ? "active" : ""}
            title={m.title}
            aria-label={m.title}
            aria-disabled={!m.enabled}
            aria-pressed={tool === id}
            onClick={() => { if (m.enabled) onTool(id); }}
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
