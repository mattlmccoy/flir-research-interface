import { DEFAULT_ISOTHERM, parseIsotherm, type Isotherm } from "./isotherm.ts";
/** Studio layout state (spec §3): which panels are open, which rail sections, which tool, image zoom. */
import { isZoom, type Zoom } from "./zoom.ts";
export const TOOLS = ["select", "spot", "rect", "circle", "line", "polygon"] as const;
const isDelta = (v: unknown): v is { a: number; b: number } => !!v && typeof v === "object" && Number.isInteger((v as { a: unknown }).a) && Number.isInteger((v as { b: unknown }).b);
export interface Agc { mode: "linear" | "plateau"; plateau: number; }
function parseAgc(v: unknown): Agc {
  const o = (v ?? {}) as Record<string, unknown>;
  const mode = o.mode === "plateau" ? "plateau" : "linear";
  const p = typeof o.plateau === "number" && Number.isFinite(o.plateau) ? Math.min(1, Math.max(0, o.plateau)) : 0.5;
  return { mode, plateau: p };
}
export interface FloatRect { x: number; y: number; w: number; h: number; }
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
function clampRect(r: FloatRect): FloatRect {
  return { x: Math.max(0, r.x), y: Math.max(0, r.y), w: Math.max(260, r.w), h: Math.max(160, r.h) };
}
function parseFloating(v: unknown): Partial<Record<Section, FloatRect>> {
  const out: Partial<Record<Section, FloatRect>> = {};
  if (!v || typeof v !== "object") return out;
  for (const [k, r] of Object.entries(v as Record<string, unknown>)) {
    const q = r as Record<string, unknown> | null;
    if ((SECTIONS as readonly string[]).includes(k) && q && isNum(q.x) && isNum(q.y) && isNum(q.w) && isNum(q.h)) out[k as Section] = clampRect({ x: q.x, y: q.y, w: q.w, h: q.h });
  }
  return out;
}
export const SECTIONS = ["measurements", "profile", "camera", "experiment", "recording", "display", "export", "visible"] as const;
export type Tool = (typeof TOOLS)[number];
export type Panel = "strip" | "rail" | "dock";
export type Section = (typeof SECTIONS)[number];

export interface LayoutState {
  strip: boolean;
  rail: boolean;
  dock: boolean;
  tool: Tool;
  zoom: Zoom;
  /** Where the visible camera shows: small in the rail, beside the thermal image, or blended over it. */
  visibleMode: VisibleMode;
  /** Draw ▲ hottest / ▽ coldest pixel markers inside area ROIs. */
  extremes: boolean;
  /** Isotherm painting over the palette (live + playback). */
  isotherm: Isotherm;
  /** Plot an extra trace A − B (ROI ids), or null. */
  delta: { a: number; b: number } | null;
  /** Rail sections popped out into floating, resizable windows (viewport px). */
  floating: Partial<Record<Section, FloatRect>>;
  /** Software image flip (display only). */
  flipH: boolean; flipV: boolean;
  /** Temporal hold: show the per-pixel max/min since reset instead of the live frame. */
  hold: "off" | "max" | "min";
  /** Automatic gain control: linear palette mapping or plateau equalisation (0..1 strength). */
  agc: Agc;
  /** Overlay registration: opacity 0–1, scale 0.5–2 and offsets in % of the image (visible lens ≠ IR lens). */
  overlay: Overlay;
  sections: Record<Section, boolean>;
}
export const VISIBLE_MODES = ["rail", "side", "overlay"] as const;
export type VisibleMode = (typeof VISIBLE_MODES)[number];
export interface Overlay { opacity: number; scale: number; dx: number; dy: number; }
export const DEFAULT_OVERLAY: Overlay = Object.freeze({ opacity: 0.5, scale: 1, dx: 0, dy: 0 }) as Overlay;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export function clampOverlay(o: Overlay): Overlay {
  return { opacity: clamp(o.opacity, 0, 1), scale: clamp(o.scale, 0.5, 2), dx: clamp(o.dx, -50, 50), dy: clamp(o.dy, -50, 50) };
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
  zoom: "fit",
  visibleMode: "rail",
  extremes: true,
  isotherm: DEFAULT_ISOTHERM,
  delta: null,
  floating: {},
  flipH: false,
  flipV: false,
  hold: "off",
  agc: { mode: "linear", plateau: 0.5 },
  overlay: DEFAULT_OVERLAY,
  sections: { measurements: true, profile: false, camera: true, experiment: true, recording: true, display: true, export: true, visible: true },
};
Object.freeze(DEFAULT_LAYOUT.sections);
Object.freeze(DEFAULT_LAYOUT);

export type LayoutAction =
  | { type: "toggle"; panel: Panel }
  | { type: "toggleSection"; section: Section }
  | { type: "openSection"; section: Section }
  | { type: "setTool"; tool: Tool }
  | { type: "setZoom"; zoom: Zoom }
  | { type: "setExtremes"; on: boolean }
  | { type: "setIsotherm"; isotherm: Isotherm }
  | { type: "setDelta"; delta: { a: number; b: number } | null }
  | { type: "popOut"; section: Section }
  | { type: "moveFloat"; section: Section; rect: FloatRect }
  | { type: "dockBack"; section: Section }
  | { type: "setFlip"; h: boolean; v: boolean }
  | { type: "setHold"; hold: "off" | "max" | "min" }
  | { type: "setAgc"; agc: Agc }
  | { type: "setVisibleMode"; mode: VisibleMode }
  | { type: "setOverlay"; patch: Partial<Overlay> }
  | { type: "collapseAll" }
  | { type: "restoreAll" };

/** Applies one LayoutAction to a LayoutState, returning a new state without mutating the input. */
export function layoutReducer(s: LayoutState, a: LayoutAction): LayoutState {
  switch (a.type) {
    case "toggle": return { ...s, [a.panel]: !s[a.panel] };
    case "toggleSection": return { ...s, sections: { ...s.sections, [a.section]: !s.sections[a.section] } };
    case "openSection": return { ...s, rail: true, sections: { ...s.sections, [a.section]: true } };
    case "setTool": return { ...s, tool: a.tool };
    case "setZoom": return { ...s, zoom: a.zoom };
    case "setVisibleMode": return { ...s, visibleMode: a.mode };
    case "setExtremes": return { ...s, extremes: a.on };
    case "setIsotherm": return { ...s, isotherm: parseIsotherm(a.isotherm) };
    case "setDelta": return { ...s, delta: a.delta };
    case "popOut": {
      const n = Object.keys(s.floating).length;
      return { ...s, floating: { ...s.floating, [a.section]: s.floating[a.section] ?? { x: 80 + n * 30, y: 80 + n * 30, w: 420, h: 360 } } };
    }
    case "moveFloat": return { ...s, floating: { ...s.floating, [a.section]: clampRect(a.rect) } };
    case "setFlip": return { ...s, flipH: a.h, flipV: a.v };
    case "setHold": return { ...s, hold: a.hold };
    case "setAgc": return { ...s, agc: parseAgc(a.agc) };
    case "dockBack": { const { [a.section]: _gone, ...rest } = s.floating; return { ...s, floating: rest }; }
    case "setOverlay": return { ...s, overlay: clampOverlay({ ...s.overlay, ...a.patch }) };
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

function isVisibleMode(v: unknown): v is VisibleMode {
  return typeof v === "string" && (VISIBLE_MODES as readonly string[]).includes(v);
}
function num(v: unknown, fallback: number): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
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
    const ov = asRecord(parsed.overlay);
    return {
      strip: bool(parsed.strip, DEFAULT_LAYOUT.strip),
      rail: bool(parsed.rail, DEFAULT_LAYOUT.rail),
      dock: bool(parsed.dock, DEFAULT_LAYOUT.dock),
      tool: isTool(parsed.tool) ? parsed.tool : DEFAULT_LAYOUT.tool,
      zoom: isZoom(parsed.zoom) ? parsed.zoom : DEFAULT_LAYOUT.zoom,
      visibleMode: isVisibleMode(parsed.visibleMode) ? parsed.visibleMode : parsed.visibleSide === true ? "side" : DEFAULT_LAYOUT.visibleMode,
      extremes: typeof parsed.extremes === "boolean" ? parsed.extremes : DEFAULT_LAYOUT.extremes,
      isotherm: parseIsotherm(parsed.isotherm),
      delta: isDelta(parsed.delta) ? parsed.delta : null,
      floating: parseFloating(parsed.floating),
      flipH: parsed.flipH === true,
      flipV: parsed.flipV === true,
      hold: "off",
      agc: parseAgc(parsed.agc),
      overlay: clampOverlay({
        opacity: num(ov.opacity, DEFAULT_OVERLAY.opacity),
        scale: num(ov.scale, DEFAULT_OVERLAY.scale),
        dx: num(ov.dx, DEFAULT_OVERLAY.dx),
        dy: num(ov.dy, DEFAULT_OVERLAY.dy),
      }),
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
