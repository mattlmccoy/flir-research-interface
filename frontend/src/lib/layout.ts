/** Studio layout state (spec §3): which panels are open, which rail sections, which tool. */
export const TOOLS = ["select", "spot", "rect", "circle", "line", "polygon"] as const;
export const SECTIONS = ["measurements", "camera", "experiment", "recording", "display", "export"] as const;
export type Tool = (typeof TOOLS)[number];
export type Panel = "strip" | "rail" | "dock";
export type Section = (typeof SECTIONS)[number];

export interface LayoutState {
  strip: boolean;
  rail: boolean;
  dock: boolean;
  tool: Tool;
  sections: Record<Section, boolean>;
}

/**
 * Computes the Studio grid's className and per-panel visibility from layout flags and which
 * slots actually have content. A panel only shows when both the layout flag is open AND the
 * caller supplied content for it (`has*`); `page` mode always suppresses strip and dock.
 */
export function studioClasses(
  layout: LayoutState,
  opts: { page: boolean; hasStrip: boolean; hasRail: boolean; hasDock: boolean },
): { className: string; showStrip: boolean; showRail: boolean; showDock: boolean } {
  const { page, hasStrip, hasRail, hasDock } = opts;
  const showStrip = !page && layout.strip && hasStrip;
  const showRail = layout.rail && hasRail;
  const showDock = !page && layout.dock && hasDock;
  const className = ["studio", page ? "page" : "", showStrip ? "" : "no-strip", showRail ? "" : "no-rail", showDock ? "" : "no-dock"]
    .filter(Boolean).join(" ");
  return { className, showStrip, showRail, showDock };
}

export const DEFAULT_LAYOUT: LayoutState = {
  strip: true,
  rail: true,
  dock: true,
  tool: "select",
  sections: { measurements: true, camera: true, experiment: true, recording: true, display: true, export: true },
};
Object.freeze(DEFAULT_LAYOUT.sections);
Object.freeze(DEFAULT_LAYOUT);

export type LayoutAction =
  | { type: "toggle"; panel: Panel }
  | { type: "toggleSection"; section: Section }
  | { type: "openSection"; section: Section }
  | { type: "setTool"; tool: Tool }
  | { type: "collapseAll" }
  | { type: "restoreAll" };

/** Applies one LayoutAction to a LayoutState, returning a new state without mutating the input. */
export function layoutReducer(s: LayoutState, a: LayoutAction): LayoutState {
  switch (a.type) {
    case "toggle": return { ...s, [a.panel]: !s[a.panel] };
    case "toggleSection": return { ...s, sections: { ...s.sections, [a.section]: !s.sections[a.section] } };
    case "openSection": return { ...s, rail: true, sections: { ...s.sections, [a.section]: true } };
    case "setTool": return { ...s, tool: a.tool };
    case "collapseAll": return { ...s, strip: false, rail: false, dock: false };
    case "restoreAll": return { ...s, strip: true, rail: true, dock: true };
  }
}

const KEY = "fri.layout.v1";

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function bool(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function isTool(v: unknown): v is Tool {
  return typeof v === "string" && (TOOLS as readonly string[]).includes(v);
}

/** Reads and validates the persisted layout from storage; any missing, malformed, or unknown field falls back to DEFAULT_LAYOUT's value. */
export function loadLayout(storage: Storage | null): LayoutState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = asRecord(JSON.parse(raw));
    const sec = asRecord(parsed.sections);
    return {
      strip: bool(parsed.strip, DEFAULT_LAYOUT.strip),
      rail: bool(parsed.rail, DEFAULT_LAYOUT.rail),
      dock: bool(parsed.dock, DEFAULT_LAYOUT.dock),
      tool: isTool(parsed.tool) ? parsed.tool : DEFAULT_LAYOUT.tool,
      sections: Object.fromEntries(
        SECTIONS.map((k) => [k, bool(sec[k], DEFAULT_LAYOUT.sections[k])]),
      ) as Record<Section, boolean>,
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

/** Persists the layout to storage as JSON, silently ignoring a storage failure (quota, disabled, security error). */
export function saveLayout(storage: Storage | null, s: LayoutState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable: ignore */ }
}
