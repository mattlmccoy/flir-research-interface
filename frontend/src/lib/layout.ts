/** Studio layout state (spec §3): which panels are open, which rail sections, which tool. */
export type Tool = "select" | "spot" | "rect" | "line" | "display" | "camera" | "nuc";
export type Panel = "strip" | "rail" | "dock";
export type Section = "measurements" | "camera" | "experiment" | "recording" | "display";

export interface LayoutState {
  strip: boolean;
  rail: boolean;
  dock: boolean;
  tool: Tool;
  sections: Record<Section, boolean>;
}

export const DEFAULT_LAYOUT: LayoutState = {
  strip: true,
  rail: true,
  dock: true,
  tool: "select",
  sections: { measurements: true, camera: true, experiment: true, recording: true, display: true },
};

export type LayoutAction =
  | { type: "toggle"; panel: Panel }
  | { type: "toggleSection"; section: Section }
  | { type: "setTool"; tool: Tool }
  | { type: "collapseAll" }
  | { type: "restoreAll" };

export function layoutReducer(s: LayoutState, a: LayoutAction): LayoutState {
  switch (a.type) {
    case "toggle": return { ...s, [a.panel]: !s[a.panel] };
    case "toggleSection": return { ...s, sections: { ...s.sections, [a.section]: !s.sections[a.section] } };
    case "setTool": return { ...s, tool: a.tool };
    case "collapseAll": return { ...s, strip: false, rail: false, dock: false };
    case "restoreAll": return { ...s, strip: true, rail: true, dock: true };
  }
}

const KEY = "fri.layout.v1";

export function loadLayout(storage: Storage | null): LayoutState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<LayoutState>;
    return {
      ...DEFAULT_LAYOUT,
      ...parsed,
      sections: { ...DEFAULT_LAYOUT.sections, ...(parsed.sections ?? {}) },
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function saveLayout(storage: Storage | null, s: LayoutState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable: ignore */ }
}
